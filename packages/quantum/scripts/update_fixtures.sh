#!/bin/bash
export UPDATE_FIXTURES=1
export PYTHONPATH=$PYTHONPATH:$(pwd)
pytest packages/quantum/tests/agents/regression
