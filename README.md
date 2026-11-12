Storing little things I need for various harness/orchestration mini-tasks.


## opencode_model_picker
Little textual-based python TUI which lists all the free io models being offered through OpenCode. If you weren't aware, OpenCode offers free models for use with their harness, but they don't really give the user any info when picking the model through the OC slash command - just the names of the models.
This script will open up a window listing the currently available free models as well as their context lengths, output limits, modalities, and reasoning support. Helps to make an informed choice.
Quite simple.

#### Requirements

- Python 3.10+
- `pip install textual httpx`

#### Config

Writes to `~/.config/opencode/opencode.json` by default. Override with:

```bash
export OPENCODE_CONFIG=/path/to/opencode.json
```

#### Run

```bash
python opencode_free_model_picker.py
```
