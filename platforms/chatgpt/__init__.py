def invite_chatgpt_team_member(*args, **kwargs):
    from .team_workspace import invite_chatgpt_team_member as _invite_chatgpt_team_member

    return _invite_chatgpt_team_member(*args, **kwargs)


def remove_chatgpt_team_member(*args, **kwargs):
    from .team_workspace import remove_chatgpt_team_member as _remove_chatgpt_team_member

    return _remove_chatgpt_team_member(*args, **kwargs)

__all__ = [
    "invite_chatgpt_team_member",
    "remove_chatgpt_team_member",
]
