#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

from dotenv import load_dotenv
from pipecat.runner.types import RunnerArguments

from ariadne.transport import create_transport
from ariadne.pipeline import run_bot

load_dotenv(override=True)


async def bot(runner_args: RunnerArguments):
    transport = create_transport(runner_args)
    if transport is None:
        return

    await run_bot(transport)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
