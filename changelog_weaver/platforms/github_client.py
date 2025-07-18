"""This module contains the GitHub platform client implementation."""

from typing import List, Optional
from dataclasses import dataclass, field
from github import Github
from .platform_client import PlatformClient
from ..typings import WorkItem, WorkItemType, HierarchicalWorkItem, CommitInfo
from .github_api import GitHubAPI


@dataclass
class GitHubConfig:
    """Configuration class for the GitHub platform."""

    access_token: str
    repo_name: str
    branch: Optional[str] = None
    from_tag: Optional[str] = None
    to_tag: Optional[str] = None
    # Add these two lines
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    client: Github = field(init=False)

    def __post_init__(self):
        self.client = Github(self.access_token)


class GitHubPlatformClient(PlatformClient):
    """GitHub platform client class."""

    def __init__(self, config: GitHubConfig):
        self.config = config
        self.api = GitHubAPI(config)

    async def initialize(self):
        await self.api.initialize()

    async def close(self):
        # GitHub API doesn't require explicit closing
        pass

    async def get_work_item_by_id(self, item_id: int) -> WorkItem:
        return await self.api.get_issue_by_number(item_id)

    async def get_work_items_from_query(self, query_id: str) -> List[WorkItem]:
        return await self.api.get_issues_from_query(query_id)

    async def get_work_items_with_details(self, **kwargs) -> List[HierarchicalWorkItem]:
        return await self.api.get_all_work_items(**kwargs)

    def get_all_work_item_types(self) -> List[WorkItemType]:
        return self.api.get_all_issue_types()

    def get_work_item_type(self, type_name: str) -> Optional[WorkItemType]:
        return self.api.get_issue_type(type_name)

    async def get_commits(self, **kwargs) -> List[CommitInfo]:
        # Add tag information from platform config if not provided in kwargs
        if "from_tag" not in kwargs and self.config.from_tag:
            kwargs["from_tag"] = self.config.from_tag
        if "to_tag" not in kwargs and self.config.to_tag:
            kwargs["to_tag"] = self.config.to_tag
        return await self.api.get_commits(**kwargs)

    @property
    def root_work_item_type(self) -> str:
        return ""  # GitHub doesn't have a concept of root work item type
