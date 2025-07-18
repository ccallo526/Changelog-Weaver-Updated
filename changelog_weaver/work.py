"""Work module for changelog-weaver"""

from typing import Dict, List, Union, Optional
import asyncio
import time
from .configuration import Config
from .typings import (
    HierarchicalWorkItem,
    WorkItemGroup,
    Platform,
    WorkItem,
    WorkItemType,
    CommitInfo,
)
from .platforms import (
    PlatformClient,
    DevOpsPlatformClient,
    GitHubPlatformClient,
    DevOpsConfig,
    GitHubConfig,
)
from .utilities import Hierarchy
from .logger import get_logger

log = get_logger(__name__)


class Work:
    """Class for fetching and summarizing work items from the platform."""

    def __init__(self, config: Config):
        self.config = config
        self.all: Dict[int, HierarchicalWorkItem] = {}
        self.root_items: List[HierarchicalWorkItem] = []
        self.by_type: List[WorkItemGroup] = []
        self.item_ids: List[int] = []
        self.platform = config.project.platform
        self.client = self._create_platform_client(config)

    def _create_platform_client(self, config: Config) -> PlatformClient:
        if self.platform.platform == Platform.AZURE_DEVOPS:
            return DevOpsPlatformClient(
                DevOpsConfig(
                    url=config.project.platform.base_url,
                    org=config.project.platform.organization,
                    project=config.project.ref,
                    query=config.project.platform.query,
                    pat=config.project.platform.access_token,
                    repo_name=config.project.platform.repo_name,
                )
            )
        if self.platform.platform == Platform.GITHUB:
            log.info(
                f"Creating GitHub client with branch: {config.project.platform.branch}, "
                f"from_tag: {config.project.platform.from_tag}, to_tag: {config.project.platform.to_tag}"
            )
            return GitHubPlatformClient(
                GitHubConfig(
                    access_token=config.project.platform.access_token,
                    repo_name=config.project.ref,
                    branch=config.project.platform.branch,
                    from_tag=config.project.platform.from_tag,
                    to_tag=config.project.platform.to_tag,
                    # Add these two lines to pass the dates
                    from_date=config.project.platform.from_date,
                    to_date=config.project.platform.to_date,
                )
            )
        raise ValueError(f"Unsupported platform: {self.platform}")

    async def initialize(self):
        """Initialize the platform client."""
        log.info("Initializing Work class")
        start_time = time.time()
        await self.client.initialize()
        end_time = time.time()
        log.info(f"Work class initialized in {end_time - start_time} seconds")

    async def close(self):
        """Close the platform client."""
        await self.client.close()

    async def summarize_work_item(self, wi: WorkItem) -> WorkItem:
        """
        Summarize a work item.

        This method skips summarization for commit items and only processes
        other types of work items if summarization is enabled in the configuration.

        Args:
            wi (WorkItem): The work item to summarize.

        Returns:
            WorkItem: The work item, potentially with a new summary.
        """
        # Skip summarization for commit items
        if wi.type.lower() == "commit":
            return wi

        if not self.config.model.item_summary:
            log.info("Skipping work item summary due to configuration setting")
            return wi

        log.info(f"Summarizing work item {wi.id}")
        item_prompt: str = self.config.prompts.item
        prompt = f"{item_prompt}: {wi.title} item type: {wi.type} {wi.description} {wi.comments}"
        wi.summary = await self.config.model.summarise(prompt)
        return wi

    async def summarize_changelog(self, changelog: List[HierarchicalWorkItem]) -> str:
        """Summarize the changelog."""
        if not self.config.model.changelog_summary:
            log.info("Skipping changelog summary due to configuration setting")
            return ""
        software_prompt: str = self.config.prompts.summary
        software_brief: str = self.config.project.brief
        prompt = (
            f"{software_prompt}{software_brief}\n"
            f"The following is a summary of the work items completed in this release:\n"
            f"{changelog}\nYour response should be as concise as possible"
        )
        return await self.config.model.summarise(prompt)

    def add(self, work_item: WorkItem) -> HierarchicalWorkItem:
        """Add a work item to the collection."""
        if work_item.id not in self.all:
            hierarchical_item = HierarchicalWorkItem(**work_item.__dict__)
            self.all[work_item.id] = hierarchical_item
        return self.all[work_item.id]

    async def get_item_by_id(self, item_id: Union[int, str]) -> HierarchicalWorkItem:
        """Get a work item by ID."""
        item = await self.client.get_work_item_by_id(int(item_id))
        return self.add(item)

    async def get_items_from_query(self, query_id: str) -> List[HierarchicalWorkItem]:
        """Get work items from a query."""
        items = await self.client.get_work_items_from_query(query_id)
        return [self.add(item) for item in items]

    async def get_items_with_details(self, **kwargs) -> List[HierarchicalWorkItem]:
        """
        Get work items with details from the platform.

        Returns:
            List[HierarchicalWorkItem]: A list of work items with their details.
        """
        log.info("Starting to fetch work items with details")
        start_time = time.time()
        items = await self.client.get_work_items_with_details(**kwargs)
        if self.platform.platform == Platform.GITHUB:
            self.root_items = [self.add(item) for item in items]
            for root_item in self.root_items:
                for child in root_item.children:
                    self.all[child.id] = child
                    self.item_ids.append(child.id)
        else:  # Azure DevOps
            self.item_ids = [item.id for item in items]
            log.info("Fetched %s work items from client", len(items))
            add_tasks = [self.get_item_by_id(item.id) for item in items]
            await asyncio.gather(*add_tasks)
            log.info("Added %s items to the work item collection", len(add_tasks))
            await self._fetch_parents()
            log.info("Fetched parent items")
            self._create_other_parent()
            log.info("Created 'Other' parent for orphaned items")

        if self.config.model.item_summary:
            summary_tasks = [
                self.summarize_work_item(item)
                for item in self.all.values()
                if item.id in self.item_ids and item.type.lower() != "commit"
            ]
            await asyncio.gather(*summary_tasks)

        if self.platform.platform == Platform.AZURE_DEVOPS:
            hierarchy = Hierarchy(self.all)
            self.root_items = hierarchy.root_items
            self.by_type = hierarchy.by_type
        else:
            self.by_type = [
                WorkItemGroup(
                    type=root_item.type, icon=root_item.icon, items=root_item.children
                )
                for root_item in self.root_items
            ]

        log.info(f"Total root items: {len(self.root_items)}")
        log.info(f"Total by_type groups: {len(self.by_type)}")
        end_time = time.time()
        log.info(
            "Fetched and processed work items in %.2f seconds", end_time - start_time
        )
        return self.root_items

    def _convert_commit_to_work_item(self, commit: CommitInfo) -> HierarchicalWorkItem:
        """
        Convert a CommitInfo object to a HierarchicalWorkItem.

        Args:
            commit (CommitInfo): The commit information to convert.

        Returns:
            HierarchicalWorkItem: The converted work item representing the commit.
        """
        return HierarchicalWorkItem(
            id=hash(commit.sha),  # Use hash of SHA as ID
            type="Commit",
            state="N/A",
            title=commit.message,
            icon="https://raw.githubusercontent.com/Hankanman/Changelog-Weaver/refs/heads/main/assets/commit-icon.svg",
            root=False,
            orphan=True,
            url=commit.url,
            sha=commit.sha,
            author=commit.author,
            date=commit.date,
            children=[],  # Commits don't have children
        )

    async def _fetch_parents(self):
        if self.platform.platform != Platform.AZURE_DEVOPS:
            return
        log.info("Starting to fetch parent items")
        start_time = time.time()
        items_to_fetch = set()
        items_list = list(self.all.values())
        for item in items_list:
            current_item = item
            while current_item.parent_id and current_item.parent_id not in self.all:
                items_to_fetch.add(current_item.parent_id)
                current_item = await self.get_item_by_id(current_item.parent_id)
        log.info(f"Fetching {len(items_to_fetch)} parent items")
        batch_size = 10
        for i in range(0, len(items_to_fetch), batch_size):
            batch = list(items_to_fetch)[i : i + batch_size]
            parent_fetch_tasks = [self.get_item_by_id(parent_id) for parent_id in batch]
            await asyncio.gather(*parent_fetch_tasks)
        end_time = time.time()
        log.info(f"Fetched parent items in {end_time - start_time:.2f} seconds")

    def _create_other_parent(self):
        if self.platform.platform == Platform.GITHUB:
            return  # GitHub doesn't need an "Other" parent
        orphaned_items = [
            item for item in self.all.values() if item.orphan and item.id != 0
        ]
        if orphaned_items:
            log.info("Creating 'Other' work item for orphaned items")
            other_parent = HierarchicalWorkItem(
                type="Other",
                root=True,
                orphan=False,
                id=0,
                title="Other",
                state="Other",
                comment_count=0,
                parent_id=0,
                icon="https://tfsproduks1.visualstudio.com/_apis/wit/workItemIcons/icon_review?color=333333&v=2",
            )
            other_parent.children = orphaned_items
            self.all[0] = other_parent
            for item in orphaned_items:
                item.parent_id = 0

    async def generate_ordered_work_items(self) -> List[WorkItemGroup]:
        """
        Generate ordered work items including commits if specified.

        Returns:
            List[WorkItemGroup]: A list of ordered work item groups.
        """
        log.info("Generating ordered work items")
        start_time = time.time()
        if not self.by_type:
            await self.get_items_with_details()

        # Handle commits for both platforms
        if self.config.include_commits and not any(
            group.type == "Commit" for group in self.by_type
        ):
            log.info("Fetching commits...")
            commits = await self.client.get_commits()
            log.info(f"Retrieved {len(commits)} commits")
            commit_items = [
                self._convert_commit_to_work_item(commit) for commit in commits
            ]
            commits_group = WorkItemGroup(
                type="Commit",
                icon="https://raw.githubusercontent.com/Hankanman/Changelog-Weaver/refs/heads/main/assets/commit-icon.svg",
                items=commit_items,
            )
            self.by_type.append(commits_group)
            log.info(f"Added commits group with {len(commit_items)} commits")

        end_time = time.time()
        log.info(f"Generated ordered work items in {end_time - start_time:.2f} seconds")
        return self.by_type

    def get_work_item_types(self) -> List[WorkItemType]:
        """Get all work item types"""
        return self.client.get_all_work_item_types()

    def get_work_item_type(self, type_name: str) -> Optional[WorkItemType]:
        """Get a work item type"""
        return self.client.get_work_item_type(type_name)
