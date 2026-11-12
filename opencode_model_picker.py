#!/usr/bin/env python3
"""
opencode_free_model_picker.py

Interactive TUI for selecting a free OpenCode model and persisting it to
~/.config/opencode/opencode.json (or $OPENCODE_CONFIG).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ZEN_MODELS_URL = "https://opencode.ai/zen/v1/models"
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "opencode" / "opencode.json"


def get_config_path() -> Path:
    env = os.getenv("OPENCODE_CONFIG")
    return Path(env).expanduser() if env else DEFAULT_CONFIG_PATH


# ---------------------------------------------------------------------------
# Fetch live models and keep only those whose cost is zero
# ---------------------------------------------------------------------------
def fetch_free_models() -> List[Dict[str, Any]]:
    """
    GET /zen/v1/models and return models where
    cost.text.input.price == 0 and cost.text.output.price == 0.
    """
    try:
        resp = httpx.get(ZEN_MODELS_URL, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        print(f"Failed to fetch live model list: {exc}", file=sys.stderr)
        sys.exit(1)

    raw_models = payload.get("data", [])
    if not isinstance(raw_models, list):
        print("Unexpected response shape from /zen/v1/models", file=sys.stderr)
        sys.exit(1)

    free: List[Dict[str, Any]] = []
    for entry in raw_models:
        cost = entry.get("cost") or {}
        text_cost = cost.get("text") or {}
        input_price = (text_cost.get("input") or {}).get("price") or 0
        output_price = (text_cost.get("output") or {}).get("price") or 0

        if input_price == 0 and output_price == 0:
            limit = entry.get("limit") or {}
            modalities = entry.get("modalities") or {}
            capabilities = entry.get("capabilities") or {}
            free.append(
                {
                    "id": entry.get("id"),
                    "name": entry.get("name") or entry.get("id"),
                    "description": entry.get("description") or "",
                    "context": limit.get("context", 0),
                    "output": limit.get("output", 0),
                    "reasoning": capabilities.get("reasoning", {}).get("supported", False),
                    "input_modalities": modalities.get("input", []),
                    "output_modalities": modalities.get("output", []),
                }
            )

    if not free:
        print("No models with zero cost found in the live catalog.", file=sys.stderr)
        sys.exit(1)

    free.sort(key=lambda m: m["name"].lower())
    return free


# ---------------------------------------------------------------------------
# Config writer
# ---------------------------------------------------------------------------
def save_model_choice(model_id: str) -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    config: Dict[str, Any] = {}
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as fh:
                config = json.load(fh)
        except json.JSONDecodeError as exc:
            print(f"Warning: could not parse existing config ({exc}).", file=sys.stderr)

    config.setdefault("$schema", "https://opencode.ai/config.json")
    config["model"] = f"opencode/{model_id}"

    with path.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"\n✅  Default model set to opencode/{model_id}")
    print(f"    Written to {path}")


# ---------------------------------------------------------------------------
# Textual UI
# ---------------------------------------------------------------------------
class ModelPickerApp(App):
    CSS = """
    Screen { layout: horizontal; }

    #sidebar {
        width: 40;
        border: solid $accent;
        padding: 0 1;
    }

    #details {
        width: 1fr;
        border: solid $secondary;
        padding: 1 2;
        layout: vertical;
    }

    ListView { height: 1fr; }
    ListItem { padding: 0 1; }
    ListItem > Label { width: 100%; text-wrap: wrap; }

    .title { text-style: bold; margin-bottom: 1; }

    #detail-pane {
        height: 1fr;
        overflow-y: auto;
    }

    #status-pane {
        height: auto;
        padding-top: 1;
        margin-top: 1;
        border-top: solid $accent;
    }
    """

    BINDINGS = [
        Binding("space", "mark_model", "Mark"),
        Binding("enter", "confirm_and_quit", "Confirm & Quit", show=True),
        Binding("q", "confirm_and_quit", "Confirm & Quit", show=True),
    ]

    def __init__(self, models: List[Dict[str, Any]]) -> None:
        super().__init__()
        self.models = models
        self.selected_model: Optional[Dict[str, Any]] = None
        self.marked_index: Optional[int] = None
        self.labels: List[Label] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Label("Free OpenCode Models", classes="title")
                items: List[ListItem] = []
                for m in self.models:
                    lbl = Label(f"  {m['name']}")
                    item = ListItem(lbl)
                    item.model = m  # type: ignore[attr-defined]
                    items.append(item)
                    self.labels.append(lbl)
                yield ListView(*items, id="model-list")
            with Vertical(id="details"):
                yield Static("", id="detail-pane")
                yield Static("", id="status-pane")
        yield Footer()

    # ---- lifecycle --------------------------------------------------------
    def on_mount(self) -> None:
        lv = self.query_one("#model-list", ListView)
        if self.models:
            lv.index = 0
            self._show_details(self.models[0])
        self._update_status()

    # ---- list events ------------------------------------------------------
    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is not None:
            self._show_details(event.item.model)  # type: ignore[attr-defined]

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        # Enter pressed while ListView has focus.
        self._do_confirm()

    # ---- actions ----------------------------------------------------------
    def action_mark_model(self) -> None:
        lv = self.query_one("#model-list", ListView)
        if lv.index is None:
            return
        if self.marked_index == lv.index:
            self.marked_index = None
        else:
            self.marked_index = lv.index
        self._refresh_markers()
        self._update_status()

    def action_confirm_and_quit(self) -> None:
        self._do_confirm()

    # ---- helpers ----------------------------------------------------------
    def _do_confirm(self) -> None:
        lv = self.query_one("#model-list", ListView)
        if self.marked_index is not None:
            self.selected_model = self.models[self.marked_index]
        elif lv.index is not None:
            self.selected_model = self.models[lv.index]
        self.exit()

    def _refresh_markers(self) -> None:
        for i, lbl in enumerate(self.labels):
            name = self.models[i]["name"]
            if i == self.marked_index:
                lbl.update(f"[bold green]●[/bold green] {name}")
            else:
                lbl.update(f"  {name}")

    def _update_status(self) -> None:
        status = self.query_one("#status-pane", Static)
        if self.marked_index is not None:
            name = self.models[self.marked_index]["name"]
            status.update(
                f"[green]● Marked:[/green] [bold]{name}[/bold]"
                f"   [dim](Enter or q to confirm)[/dim]"
            )
        else:
            status.update(
                "[dim]No model marked.  "
                "Press [bold]Space[/bold] to mark the highlighted model, "
                "[bold]Enter[/bold] or [bold]q[/bold] to confirm.[/dim]"
            )

    def _show_details(self, m: Dict[str, Any]) -> None:
        pane = self.query_one("#detail-pane", Static)
        in_mods = ", ".join(m["input_modalities"]) or "—"
        out_mods = ", ".join(m["output_modalities"]) or "—"

        text = (
            f"[bold]{m['name']}[/bold]\n\n"
            f"{m['description'] or 'No description available.'}\n\n"
            f"[bold]Context window:[/bold] {m['context']:,} tokens\n"
            f"[bold]Max output:[/bold] {m['output']:,} tokens\n"
            f"[bold]Reasoning:[/bold] {'✅' if m['reasoning'] else '❌'}\n"
            f"[bold]Input modalities:[/bold] {in_mods}\n"
            f"[bold]Output modalities:[/bold] {out_mods}\n"
            f"[bold]Cost:[/bold] free (input & output = 0)"
        )
        pane.update(text)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    models = fetch_free_models()
    app = ModelPickerApp(models)
    app.run()

    if app.selected_model is None:
        print("No model selected.", file=sys.stderr)
        sys.exit(0)

    save_model_choice(app.selected_model["id"])


if __name__ == "__main__":
    main()
