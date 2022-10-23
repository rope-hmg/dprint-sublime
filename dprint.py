import sublime
import sublime_plugin
import os
import subprocess
import json
import re
import random

cached_dir_results = {}

class DprintFmtCommand(sublime_plugin.TextCommand):
	def description(self):
		return "Formats source code using dprint."

	def run(self, edit):
		try:
			if not dprint_exec.is_running():
				return

			file_path = self.view.file_name()

			if file_path is not None and dprint_exec.can_format_text(file_path):
				extension = os.path.splitext(file_path)[1].replace(".", "")
				dir_path = os.path.dirname(file_path)

				if dir_path in cached_dir_results:
					extensions = cached_dir_results[dir_path]
				else:
					plugin_infos = dprint_exec.get_plugin_info(dir_path)
					extensions = [file_ext for plugin_info in plugin_infos for file_ext in plugin_info["fileExtensions"]]
					cached_dir_results[dir_path] = extensions

				if extension in extensions:
					file_region = sublime.Region(0, self.view.size())
					file_text = self.view.substr(file_region)
					file_encoding = self.view.encoding()

					formatted_text = dprint_exec.format_text(file_path, file_text, file_encoding)

					if file_text != formatted_text:
						self.view.replace(edit, file_region, formatted_text)
						print("dprint: Formatted " + file_path)

		except Exception as err:
			print("dprint: " + str(err))

SUCCESS_RESPONSE    = 0
ERROR_RESPONSE      = 1
SHUTDOWN_SERVICE    = 2
ACTIVE              = 3
CAN_FORMAT          = 4
CAN_FORMAT_RESPONSE = 5
FORMAT              = 6
FORMAT_RESPONSE     = 7
CANCEL_FORMAT       = 8

class MessageBuilder:
	def __init__(self, message_kind):
		self.buffer = bytearray()
		self.body   = bytearray()
		self.id     = random.randint(0, 1000)
		self.kind   = message_kind
		self.buffer.extend(int_to_bytes(self.id))
		self.buffer.extend(int_to_bytes(message_kind))

	def push_int(self, int):
		self.body.extend(int_to_bytes(int))

	def push_str(self, str):
		str_bytes = bytes(str, "UTF-8")
		self.push_int(len(str_bytes))
		self.body.extend(str_bytes)

	def finish(self):
		self.buffer.extend(int_to_bytes(len(self.body)))
		self.buffer.extend(self.body)
		self.buffer.extend(int_to_bytes(0xFFFFFFFF))

class EventListener(sublime_plugin.EventListener):
	def on_init(self, views):
		dprint_exec.init_editor_service()

	def on_exit(self):
		dprint_exec.shutdown_editor_service()

	def on_pre_save(self, view):
		view.run_command("dprint_fmt")

def int_to_bytes(int_value):
	return int_value.to_bytes(4, "big")

def bytes_to_int(bytes_value):
	return int.from_bytes(bytes_value, "big", signed=False)

class DprintExec:
	def __init__(self):
		self.editor_service      = None
		self.formatted_text      = None
		self.can_format_response = False
		self.service_active  	 = False

	def get_plugin_info(self, dir_path):
		expected_schema_version = 4
		json_text = subprocess.check_output(["dprint", "editor-info"], cwd=dir_path).decode("utf8")
		editor_info = json.loads(json_text)

		if editor_info["schemaVersion"] != expected_schema_version:
			if editor_info["schemaVersion"] > expected_schema_version:
				raise Exception("Please upgrade your editor extension to be compatible with the installed version of dprint.")
			else:
				raise Exception("Your installed version of dprint is out of date. Please update it.")

		return editor_info["plugins"]

	def init_editor_service(self):
		from subprocess import Popen, PIPE

		parent_pid = str(os.getpid())

		self.editor_service = Popen(
			["dprint", "editor-service", "--parent-pid", parent_pid],
			stdin=PIPE,
			stdout=PIPE,
		)

	def shutdown_editor_service(self):
		message = MessageBuilder(SHUTDOWN_SERVICE)
		message.finish()

		self.send_message(message)

	def is_running(self):
		message = MessageBuilder(ACTIVE)
		message.finish()

		self.service_active = False
		self.send_message(message)

		return self.service_active

	def can_format_text(self, file_path):
		message = MessageBuilder(CAN_FORMAT)
		message.push_str(file_path)
		message.finish()

		self.can_format_response = False
		self.send_message(message)

		return self.can_format_response

	def format_text(self, file_path, file_text, file_encoding):
		message = MessageBuilder(FORMAT)
		message.push_str(file_path)
		message.push_int(0) # start byte index
		message.push_int(0) # end   byte index
		message.push_int(0) # override configuration byte length
		message.push_str(file_text)
		message.finish()

		self.formatted_text = None
		self.send_message(message)

		return self.formatted_text

	def send_message(self, message):
		if self.editor_service != None:
			self.editor_service.stdin.write(message.buffer)
			self.editor_service.stdin.flush()

			response_head = self.editor_service.stdout.read(12)
			response_id   = bytes_to_int(response_head[0:4])
			response_kind = bytes_to_int(response_head[4:8])
			response_len  = bytes_to_int(response_head[8:12])
			response_body = self.editor_service.stdout.read(response_len)
			success_bytes = self.editor_service.stdout.read(4)

			if bytes_to_int(success_bytes) != 0xFFFFFFFF:
				print("Oops")
			else:
				self.handle_response(response_id, response_kind, response_body, message)

	def send_error(self, message_id, error_message):
		error = MessageBuilder(ERROR_RESPONSE)
		error.push_int(message_id)
		error.push_str(error_message)

		self.send_message(error_message)


	def handle_response(self, response_id, response_kind, response_body, sent_message):
		if response_kind == SUCCESS_RESPONSE:
			self.handle_success_response(response_body, sent_message)
		elif response_kind == ERROR_RESPONSE:
			self.handle_error_response(response_body, sent_message)
		elif response_kind == ACTIVE:
			self.handle_active_message(response_id)
		elif response_kind == CAN_FORMAT_RESPONSE:
			self.handle_can_format_response(response_body, sent_message)
		elif response_kind == FORMAT_RESPONSE:
			self.handle_format_file_response(response_body, sent_message)
		else:
			# We've been sent a message that we shouldn't have:
			# * Shutdown Process 2
			# * Can Format       4
			# * Format File      6
			# * Cancel Format    8
			# * Unknown Message Kind
			self.send_error("Invalid message kind: {}".format(response_kind))

	def handle_success_response(self, response_body, send_message):
		message_id = bytes_to_int(response_body[0:4])

		if message_id == sent_message.id and sent_message.kind == ACTIVE:
			self.service_active = True

	def handle_error_response(self, response_body, send_message):
		message_id = bytes_to_int(response_body[0:4])

		if message_id == sent_message.id:
			error_len  = bytes_to_int(response_body[4:8])
			error_str  = response_body[8:8+error_len].decode("UTF-8")

			raise Exception(error_str)

	def handle_active_message(self, response_id):
		success = MessageBuilder(0)
		success.push_int(response_id)
		self.send_message(success)

	def handle_can_format_response(self, response_body, sent_message):
		message_id = bytes_to_int(response_body[0:4])
		can_format = bytes_to_int(response_body[4:8])

		if message_id == sent_message.id:
			self.can_format_response = can_format == 1

	def handle_format_file_response(self, response_body, sent_message):
		message_id   = bytes_to_int(response_body[0:4])
		needs_format = bytes_to_int(response_body[4:8])

		if message_id == sent_message.id and needs_format == 1:
			formatted_text_len  = bytes_to_int(response_body[8:12])
			self.formatted_text = response_body[12:12+formatted_text_len].decode("UTF-8")

dprint_exec = DprintExec()
