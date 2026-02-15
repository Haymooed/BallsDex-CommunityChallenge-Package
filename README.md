# BallsDex V3 Community Event Package 🎉
---

## 📦 Installation

Add the following entry to `config/extra.toml` so BallsDex installs the package automatically:

```toml
[[ballsdex.packages]]
location = "git+https://github.com/Haymooed/BallsDex-CommunityChallenge.git"
path = "event"
enabled = true
editable = false
```

The package is distributed as a standard Python package — no manual file copying required.
After adding the configuration, restart your BallsDex bot. The package will be automatically installed and migrations will be run.
