# BallsDex V3 Community Challenge Package

Community Challenge package for **BallsDex V3**. Provides cooperative server-wide goals
configured entirely from the admin panel, with progress tracking, automatic completion
announcements, and reward distribution.

## Installation (`extra.toml`)

Add this entry to `config/extra.toml`:

```toml
[[ballsdex.packages]]
location = "git+https://github.com/Haymooed/BallsDex-CommunityChallenge-Package.git"
path = "community_challenge"
enabled = true
editable = false
```

## Enabling & configuring

All configuration is handled through the admin panel — no hardcoded settings.

- **Challenge settings** (singleton):
  - Enable/disable the entire system
  - Announcement channel ID (where completions are broadcast)

- **Community Challenges**:
  - `name` — display name
  - `description` — short description shown in embeds
  - `challenge_type` — one of `collect`, `trade`, `craft`, `catch`, `donate`
  - `target_amount` — community-wide goal integer
  - `reward_item` — string key passed to your reward logic
  - `reward_quantity` — how many reward items each participant receives
  - `enabled` — toggle without deleting
  - `completed` — set automatically when progress hits target; can also be reset manually

- **Challenge Progress** entries are created/incremented automatically as players trigger
  supported events. Admins can view and inspect them for audit purposes.

## Commands

- `/challenge` — view all active challenges and their current progress
- `/challenge leaderboard` — top contributors for the currently selected challenge

## Notes

- Progress is stored in the database (persistent across restarts).
- When a challenge reaches its `target_amount` the bot announces completion in the configured
  channel, distributes rewards to all contributors, and marks it completed.
- Uses BallsDex models (`Ball`, `BallInstance`, `Player`, `Special`) and the V3 extra package
  loading flow.
- Fully async; no legacy decorators or synchronous ORM calls.
