@echo off
:: ============================================================================
:: load_env.cmd - Load environment variables from .env files
:: ============================================================================
:: Usage: call load_env.cmd [repo_root]
::
:: Loads vars from (in order, first value wins):
::   1. %REPO_ROOT%\.env.local
::   2. %REPO_ROOT%\.env
::   3. %REPO_ROOT%\packages\quantum\.env.local
::   4. %REPO_ROOT%\packages\quantum\.env
::
:: This script does NOT use setlocal, so vars persist to caller.
:: ============================================================================

:: Use provided repo root or default to two levels up from this script
if "%~1"=="" (
    pushd "%~dp0\..\.."
    set "_ENV_REPO_ROOT=%CD%"
    popd
) else (
    set "_ENV_REPO_ROOT=%~1"
)

set "_ENV_FILES_LOADED="

:: Load .env.local first (highest priority)
if exist "%_ENV_REPO_ROOT%\.env.local" (
    call :load_file "%_ENV_REPO_ROOT%\.env.local"
    set "_ENV_FILES_LOADED=%_ENV_FILES_LOADED% .env.local"
)

:: Load .env (lower priority)
if exist "%_ENV_REPO_ROOT%\.env" (
    call :load_file "%_ENV_REPO_ROOT%\.env"
    set "_ENV_FILES_LOADED=%_ENV_FILES_LOADED% .env"
)

:: Load packages/quantum/.env.local
if exist "%_ENV_REPO_ROOT%\packages\quantum\.env.local" (
    call :load_file "%_ENV_REPO_ROOT%\packages\quantum\.env.local"
    set "_ENV_FILES_LOADED=%_ENV_FILES_LOADED% quantum/.env.local"
)

:: Load packages/quantum/.env
if exist "%_ENV_REPO_ROOT%\packages\quantum\.env" (
    call :load_file "%_ENV_REPO_ROOT%\packages\quantum\.env"
    set "_ENV_FILES_LOADED=%_ENV_FILES_LOADED% quantum/.env"
)

:: Clean up temp vars
set "_ENV_REPO_ROOT="
goto :eof

:: ============================================================================
:: :load_file - Parse a .env file and set variables
:: ============================================================================
:load_file
set "_ENV_FILE=%~1"
for /f "usebackq tokens=1,* delims==" %%A in ("%_ENV_FILE%") do (
    :: Skip comments (lines starting with #) and empty lines
    set "_LINE=%%A"
    if defined _LINE (
        :: Check if line starts with # (comment)
        set "_FIRST_CHAR=!_LINE:~0,1!"
        if not "!_FIRST_CHAR!"=="#" (
            :: Only set if not already defined (first value wins)
            if not defined %%A (
                set "%%A=%%B"
            )
        )
    )
)
set "_ENV_FILE="
set "_LINE="
set "_FIRST_CHAR="
goto :eof
