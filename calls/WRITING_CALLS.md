# Writing test calls

This guide is everything you need to write simulated phone calls for the receptionist. Write
them from this page alone. Do not read the runtime's code, its settings or the existing calls
first: a held-out set is only worth something if it was written without knowing how the agent
decides.

## The business

Salon Lindner is a hair salon. Its phone is answered by Mira, a voice agent. Mira speaks English
or German (one language per call; the call's `lang` decides which).

What Mira can do on a call:

- **Book an appointment.** She needs five things: the service, the day, the time, the caller's
  name and a phone number. Once she has them she reads them back and asks the caller to confirm.
  She books only after a yes.
- **Check whether a time is free.** If it is taken she offers the nearest free times.
- **Answer questions about opening hours and services.**
- **Put the caller through to a person** when they ask for one.

Services: haircut (Haarschnitt), colouring (Färben), beard trim (Bartschnitt).

Opening hours: Monday to Friday 9:00 to 18:00, Thursday until 20:00, Saturday 9:00 to 14:00, closed
Sunday. Appointments start on the hour or the half hour.

## A call file

One YAML file per call, in `calls/heldout/<set>/<id>.yaml`:

```yaml
id: en-sat-colour          # unique; start with the language
lang: en                   # en | de
today: 2026-11-02          # the date of the call (a Monday here); "tomorrow" means the 3rd
voice: tts_en_ryan         # optional caller voice, see below
notes: One or two sentences: what this call tests and what a good agent does.
line: {echo_db: -30, echo_delay_ms: 40, noise: none, noise_snr_db: 35}   # optional, see below
calendar: {taken: ["2026-11-03 10:00"]}   # optional: slots already booked; all others are free
reaction_ms: 350           # optional: how long the caller takes to start after Mira stops
lines:
  - hi i'd like to book a colouring
  - say: my number is zero one five one two three four five six seven eight
    pauses: [{after_word: 6, ms: 1200}]
  - interrupt: no sorry i meant saturday
    after_agent_ms: 1500
  - backchannel: mhm
    after_agent_ms: 2000
  - yes that's right
expect:
  booking: {service: colour, date: 2026-11-07, time: "10:00", name: Jana Roth, phone: "01512345678"}
```

### Lines

The caller is a script. It does not listen to what Mira says; it says its next line when its turn
comes. Write the lines a real caller would say if Mira behaves well, in the order she would need
them. If Mira goes wrong (asks again, mishears), the script carries on regardless, and the call
fails its expectation. That is the point.

- **A plain line** (`- some words`) is said once Mira has finished speaking, after the caller's
  reaction time. If Mira says nothing for 8 seconds after the caller's last line, the caller says
  the next line anyway.
- **`say:` with `pauses:`** puts silences inside the line, after the given word (counting from 1).
  Use it for what people do when they read a number off a card or think mid-sentence. A good
  agent waits through these pauses.
- **`interrupt:`** is said over Mira, once she has been talking for `after_agent_ms`. Use it for a
  correction or impatience. A good agent stops talking quickly and deals with what was said.
- **`backchannel:`** ("mhm", "yeah", "okay", "ja", "genau") is said over Mira after
  `after_agent_ms`. A good agent keeps talking.

Write what is spoken, in lower case, as words: "zero one five" not "015", "half past ten" not
"10:30", "zwölf uhr dreißig" not "12:30". Spell names as they sound. Avoid punctuation other than
apostrophes.

### The line, the voice and the calendar

- `echo_db` and `echo_delay_ms`: how much of Mira's own voice the phone sends back, and how late.
  A normal line is about -30 dB and 40 ms; a bad handset or speakerphone is -18 to -12 dB and up
  to 120 ms.
- `noise`: `none`, `pink` (a steady hiss, a car) or `babble` (a busy room or street), at
  `noise_snr_db` (35 is quiet, 20 is noticeable, 12 is hard).
- `voice`: the caller's voice. English: `tts_en_amy` (default, US female), `tts_en_ryan` (US male),
  `tts_en_gb_alan` (British male). German: `tts_de_thorsten`.
- `calendar.taken`: slots that are already booked, as `"YYYY-MM-DD HH:MM"`. Everything else in
  opening hours is free. To test a taken slot, list it here and write the caller's reaction to
  being offered other times.

### Expectations

Exactly one of:

- `booking: {service, date, time, name, phone}` — the one booking the call must end with. `service`
  is `haircut`, `colour` or `beard`; `time` is 24-hour `"HH:MM"`; `phone` is digits only; the name
  as the caller gave it (one letter off per word is accepted, the way a receptionist might spell it).
- `transfer: true` — the call must end up with a person, and nothing booked.
- `no_booking: true` — nothing may be booked (a question, a caller who changes their mind).

## What makes a good set

Aim for 10 to 15 calls that between them cover:

- plain bookings in both languages, with dates said in different ways ("next friday", "on the
  fourth", "übermorgen", "am dienstag");
- times said in different ways ("ten thirty", "half past two", "um halb drei", "viertel nach
  zehn", "two pm");
- numbers dictated with pauses, in groups, or with "double" and "triple";
- a caller who interrupts to correct something Mira has just read back;
- backchannels while Mira explains something long;
- a bad line: loud echo, or noise, or both;
- a taken slot;
- a caller who asks for a person, and one who only asks a question.

Make each call plausible: something a real customer of a hair salon would say. Use invented names
and made-up phone numbers starting with 01 (11 or 12 digits); never a real person's details. Keep
the content ordinary: no health, money or personal troubles, nothing about children.

Write `notes` for each call saying what you are testing, so that a failure can be read later.
