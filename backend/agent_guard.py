"""Phase 4 - safeguards (Step 10).

The campaign agent is only allowed to do things on an explicit allow-list: call the text model, call the image
model, and read/write this app's own database and storage folder. Anything that would reach the outside world
(publishing a post, scheduling, sending an email, launching an ad, spending budget) is an *external action*:
it is blocked in code, so even a bug or a prompt-injected model reply cannot trigger it.

The only way content leaves the app is the explicit, user-confirmed export of items the user approved
(see agent_routes.export_campaign), which returns a file for MANUAL posting and is written to an audit log.
"""

ALLOWED_ACTIONS = {"llm.generate", "image.generate", "db.read", "db.write", "storage.write"}

EXTERNAL_ACTIONS = {
    "publish_post", "post_to_social", "schedule_post", "send_email", "launch_ad", "spend_budget",
}

# Cost / blast-radius limits for one run.
MAX_ASSETS_PER_RUN = 6
MAX_VARIATIONS = 3
MAX_CONCEPTS = 3


class ExternalActionBlocked(PermissionError):
    """Raised when the agent tries to do something outside its allow-list."""


def require(action: str) -> None:
    """Call before every side effect. Returns silently for allowed actions, raises for everything else."""
    if action in ALLOWED_ACTIONS:
        return
    if action in EXTERNAL_ACTIONS:
        raise ExternalActionBlocked(
            f"'{action}' is an external action. The agent never publishes or contacts outside services "
            "without explicit user approval, and direct publishing is disabled in this app."
        )
    raise ExternalActionBlocked(f"Action '{action}' is not on the agent's allow-list.")


SAFEGUARDS = [
    {"id": "no_auto_publish", "title": "Nothing is published automatically",
     "description": "The agent only creates drafts inside this app. It has no connection to Instagram, Facebook, "
                    "LinkedIn, YouTube, email or ad accounts."},
    {"id": "allow_list", "title": "Action allow-list",
     "description": "Every step is checked against a short allow-list (text AI, image AI, own database and storage). "
                    "Any other action is blocked in code."},
    {"id": "plan_review", "title": "Optional plan approval",
     "description": "Turn on 'Pause for my approval' and the agent stops after planning, before it spends any "
                    "image-generation calls, until you confirm the asset list."},
    {"id": "per_asset_approval", "title": "Per-asset approval",
     "description": "Each generated asset starts as 'pending'. Only assets you approve can be exported. "
                    "Regenerating an asset sets it back to 'pending'."},
    {"id": "confirmed_export", "title": "Confirmed export only",
     "description": "Exporting requires approved assets and an explicit confirmation. The export is a file for "
                    "manual posting and is written to the audit log."},
    {"id": "limits", "title": "Cost limits",
     "description": f"At most {MAX_ASSETS_PER_RUN} assets, {MAX_VARIATIONS} copy variations and {MAX_CONCEPTS} "
                    "image concepts per asset, and one active run per campaign."},
]
