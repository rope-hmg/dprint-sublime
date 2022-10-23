# dprint - Sublime Text Plugin

Sublime Text formatting extension for [dprint](https://dprint.dev)—a pluggable and configurable formatting platform.

## Setup

1. Install [dprint's CLI](https://dprint.dev/install).
2. Install Sublime Text plugin via [Package Control](https://packagecontrol.io/packages/dprint) *
3. Run `dprint init` in the root directory of your repository to create a configuration file.

Note, this plugin is not currently available through Package Control. The following instructions can be used as an alternative installation method:

1. In Sublime Text open the command pallete and type `Package Control: Add Repository`
2. Enter the https url to clone this repo `https://github.com/dprint/dprint-sublime.git`
3. Open the command pallete again and type `Package Control: Install Package`
4. Search for `dprint-sublime` and select

## Features

Formats code in the editor using [dprint](https://dprint.dev).

Plugins are currently resolved based on the configuration file found based on the current file (in any ancestor directory or ancestor `config` sub directory).

## Commands

* `dprint_fmt` - Formats the code being edited.
