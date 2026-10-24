# duplex-call-runtime

A voice agent that answers real phone calls: Twilio Media Streams in, streaming speech
recognition, an LLM with tools, streaming speech synthesis out, in one asyncio runtime. It
decides when the caller has finished from the words, starts the LLM before it is sure, takes a
wrong guess back, stops when interrupted, keeps talking through "mhm", cancels its own echo, and
hedges slow LLM providers. Every claim is measured from the caller's side of a simulated line.

The full write-up with results follows once the evaluation in `reports/` is complete.
