# 2. The end of a turn is decided from the words, not from silence alone

## Context

Answering after a fixed silence (the usual 700 to 1000 ms) is slow on every turn and still cuts
in when a caller pauses mid-number. Audio turn-detection models (pipecat Smart Turn) and text
models (LiveKit's turn detector, a distilled Qwen2.5-0.5B) both beat silence; their weights are on
Hugging Face, which this environment cannot reach.

## Decision

- A small logistic model over hashed features of the transcript so far (last words, word class,
  length, whether a number is half-said) and of what the agent last asked (`turn/context.py`): a
  name, a time and a phone number end differently. Trained on `turn/corpus/` (en, de), where each
  full line is a finished turn and its prefixes unfinished ones. Validation AUC 0.89. It costs
  microseconds, so it runs on every pause.
- Rules on top: a phone number still being dictated keeps the turn open up to 2.6 s; a
  complete one ends it; any turn ends after 1.4 s.
- Timing: at 60 ms of pause the recogniser is flushed; at 120 ms a likely end starts the LLM
  speculatively (no audio until committed); from 200 ms the agent may answer.
- A wrong guess is repairable: if the caller goes on before any agent audio, the reply is taken
  back silently and the turn continues. The recogniser is reset only when the reply is heard, so
  a word split by a pause ("wednes ... day") stays whole.

## Consequences

The silence baseline remains a configuration (`turn_mode: silence`), and the evaluation runs it
on the same calls. Replacing the model with an audio model is a change to `turn/model.py`
behind the same `probability(text, context)`.
