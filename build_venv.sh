#!/bin/bash
# This script will build (or rebuild) the venv required for zKillMon to run.

# Ensure the venv is in the directory of the running script.
# Fallback to python3 if the python environment variable is not present.
cd "$(dirname "$0")"
VIRTUALENV="$(pwd -P)/venv"
PYTHON="${PYTHON:-python3}"

# Validate the minimum required Python version
COMMAND="${PYTHON} -c 'import sys; exit(1 if sys.version_info < (3, 10) else 0)'"
PYTHON_VERSION=$(eval "${PYTHON} -V")
eval $COMMAND || {
  echo "--------------------------------------------------------------------"
  echo "ERROR: Unsupported Python version: ${PYTHON_VERSION}."
  echo "zKillMon requires Python 3.10 at minimum"
  echo "--------------------------------------------------------------------"
  exit 1
}
echo "Using ${PYTHON_VERSION}"

# Remove the existing virtual environment (if any)
if [ -d "$VIRTUALENV" ]; then
  COMMAND="rm -rf ${VIRTUALENV}"
  echo "Removing old virtual environment..."
  eval $COMMAND
else
  WARN_MISSING_VENV=1
fi

# Create a new virtual environment
COMMAND="${PYTHON} -m venv ${VIRTUALENV}"
echo "Creating a new virtual environment at ${VIRTUALENV}..."
eval $COMMAND || {
  echo "--------------------------------------------------------------------"
  echo "ERROR: Failed to create the virtual environment. Check that you have"
  echo "the required system packages installed and the following path is"
  echo "writable: ${VIRTUALENV}"
  echo "--------------------------------------------------------------------"
  exit 1
}

# Activate the virtual environment
source "${VIRTUALENV}/bin/activate"

# Upgrade pip
COMMAND="pip install --upgrade pip"
echo "Updating pip ($COMMAND)..."
eval $COMMAND || exit 1
pip -V

# Install necessary system packages
COMMAND="pip install wheel"
echo "Installing Python system packages ($COMMAND)..."
eval $COMMAND || exit 1

# Install required Python packages
COMMAND="pip install -r requirements.txt"
echo "Installing core dependencies ($COMMAND)..."
eval $COMMAND || exit 1

echo "Upgrade complete! Don't forget to restart the zKillMon services:"
echo "  > sudo systemctl restart zKillMon"
