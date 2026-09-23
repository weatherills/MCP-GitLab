"""PRD-08 toolset `collaboration`: project members, users, wikis, webhooks, and snippets."""

from mcp_gitlab.tools import Toolset
from mcp_gitlab.toolsets.collaboration.members import MEMBERS_TOOL
from mcp_gitlab.toolsets.collaboration.snippets import SNIPPETS_TOOL
from mcp_gitlab.toolsets.collaboration.users import USERS_TOOL
from mcp_gitlab.toolsets.collaboration.webhooks import WEBHOOKS_TOOL
from mcp_gitlab.toolsets.collaboration.wikis import WIKIS_TOOL

TOOLSET = Toolset(
    name="collaboration",
    description="Project members and roles, user lookup, project wikis, project webhooks, and "
    "snippets.",
    tools=(MEMBERS_TOOL, USERS_TOOL, WIKIS_TOOL, WEBHOOKS_TOOL, SNIPPETS_TOOL),
)
