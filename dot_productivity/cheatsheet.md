---
output: cheatsheet.html
export_on_save:
    html: true
---

<link rel="stylesheet" href="cheatsheet.css">
 <style>
html body table td, html body table th {
    padding: 0 0.5em;
 }
</style>

<div class="cheatsheet-columns">

<div class="section-group">

### iTerm2 Panes

| Function | Key |
| --- | --- |
| Split Pane V | ⌘D |
| Split Pane H | ⌘⇧D |
| Toggle Maximize Pane | ⌘⌥⇧M |

### VSCode Groups

| Function | Key |
| --- | --- |
| Toggle Maximize Pane | ⌘⌥⇧M |
| Split editor | ⌘H ⌘S *dir* |
| Focus group | ⌘H ⌘F *dir* |
| Move to group | ⌘H ⌘M *dir* |
| **Resize group** | **⌘H ⌘R** ***dir*** |
| Close all in group | ⌘K W |

### Navigation

| Function | Key |
| --- | --- |
| Jump by word | ⌥←/→ |
| Jump to line start/end | ⌘←/→ |
| Jump to matching bracket | ⌘⇧\ |

</div>

<div class="section-group">

### Editing / Selecting

| Function | Key |
| --- | --- |
| Shift Line/Block | ⌥*dir* |
| Duplicate Line/Block | ⌥⇧*dir* |
| Add Cursor | ⌥*click* |
| Add Match | ⌘D |
| Add Prev-Match | ⌘⇧D |
| Skip Match | ⌘⌥-D |
| Skip Prev-Match | ⌘⌥⇧D |

### Code Folding

| Function | Key |
| --- | --- |
| Toggle Fold Mode | ⌘H ⌘] |
| Fold region at cursor | ⌘⌥[ |
| Unfold region at cursor | ⌘⌥] |
| Fold Siblings | ⌘K ⌘[ |
| Fold all regions | ⌘K ⌘0 |
| Unfold all regions | ⌘K ⌘J |
| Fold to level 1-5 | ⌘K ⌘*num* |

</div>

<div class="section-group">

### Problems & Errors

| Function | Key |
| --- | --- |
| Error info at cursor | ⌘H ⌘E |
| Go to next error | F8 |
| Go to previous error | ⇧F8 |
| Open Problems Panel | ⌘⇧M |

### Zen/Focus Modes

| Function | Key |
| --- | --- |
| Toggle Zen Mode | ⌘K Z |
| Exit Zen Mode | ESC ESC |

#### Glyphs (Reference)

⌘ ⌃ ⌥ ⇧ ⏎
</div>

<div class="section-group tmux">

### tmux

Inside tmux, press and release the prefix (`Ctrl+b` by default), then press the listed key.

#### From the shell

| Function | Command |
| --- | --- |
| List sessions | `tmux ls` |
| Attach to session | `tmux attach -t NAME` |
| Attach to recent | `tmux attach` |
| Start named | `tmux new -s NAME` |

#### Tmux Nav

| Function | Keys |
| --- | --- |
| Detach | `d` |
| Browse wins | `w` |
| Browse sess | `s` |
| N/P win | `n` / `p` |
| Jump to win | `0`–`9` |
| New win | `c` |
| Rename S / W | `$`/`,` |
| Kill S/W/P | ``/`&`/`x` |

#### Undo a split

| Function | Keys |
| --- | --- |
| Focus a pane | `↑` `↓` `←` `→` |
| Break pane->win| `!` |
| Close pane | `x`+`y` |
| Zoom pane | `z` |

</div>  

</div>
