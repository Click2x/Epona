@echo off
rem SPDX-FileCopyrightText: 2026 The Epona contributors
rem SPDX-License-Identifier: GPL-3.0-or-later
rem Epona: double-click this to open the guided menu (pick your game file, check this PC, install). It needs only Python 3, 64-bit,
rem from python.org. Everything else is offered inside the menu, and asks before it downloads anything.
title Epona
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 goto haspy
where python >nul 2>nul
if not errorlevel 1 goto haspython
echo.
echo   Python 3 was not found on this PC.
echo   Install the 64-bit Python from https://www.python.org/downloads/ and tick "Add python.exe to PATH",
echo   then double-click this file again.
goto end
:haspy
py -I nx2\make_game.py --ui
goto end
:haspython
python -I nx2\make_game.py --ui
:end
echo.
pause
