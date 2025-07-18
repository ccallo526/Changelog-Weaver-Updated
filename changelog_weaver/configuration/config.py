""" Configuration class for the application. """

from typing import Tuple, Optional
from urllib.parse import urlparse, unquote
from ..typings import Project, Platform, PlatformInfo, Notes, ApiDetails
from .base_config import BaseConfig, ENVVARS
from .output import Output
from .prompts import Prompts
from .model import Model
from ..logger import get_logger

log = get_logger(__name__)


class Config(BaseConfig):
    """Configuration class for the application.

    Args:
        env_path (Path): The path to the .env file. Default is Path(".") / ".env".
        output_folder (str): The folder to save the output file in. Default is "Releases".
        software (Optional[Software]): The software configuration. Default is None and is self-initialized.
        devops (Optional[DevOps]): The DevOps configuration. Default is None and is self-initialized.
        model (Optional[Model]): The model configuration. Default is None and is self-initialized.
        prompts (Optional[Prompt]): The prompt configuration. Default is None and is self-initialized.
        output (Optional[Output]): The output configuration. Default is None and is self-initialized.
    """

    def __init__(
        self,
        model: Optional[Model] = None,
        prompts: Optional[Prompts] = None,
        output: Optional[Output] = None,
        project: Optional[Project] = None,
    ):
        super().__init__()
        env = self.env.variables
        try:
            self.project = project or parse_project(
                name=env.get(ENVVARS.SOLUTION_NAME, ""),
                version=env.get(ENVVARS.RELEASE_VERSION, ""),
                brief=env.get(ENVVARS.SOFTWARE_SUMMARY, ""),
                url=env.get(ENVVARS.PROJECT_URL, ""),
                query=env.get(ENVVARS.QUERY, ""),
                access_token=env.get(ENVVARS.ACCESS_TOKEN, ""),
                repo_name=env.get(ENVVARS.REPO_NAME, ""),
                branch=env.get(ENVVARS.BRANCH, ""),
                from_tag=env.get(ENVVARS.FROM_TAG, ""),
                to_tag=env.get(ENVVARS.TO_TAG, ""),
                # Add these two lines
                from_date=env.get(ENVVARS.FROM_DATE),
                to_date=env.get(ENVVARS.TO_DATE),
            )
        except ValueError as e:
            log.error("Error parsing project: %s", str(e))
            log.error(
                "PROJECT_URL from environment: %s",
                env.get(ENVVARS.PROJECT_URL, ""),
            )
            raise

        self.model = model or Model(
            api_details=ApiDetails(
                key=env.get(ENVVARS.GPT_API_KEY, ""),
                url=env.get(ENVVARS.MODEL_BASE_URL, ""),
                model_name=env.get(ENVVARS.MODEL, ""),
            ),
            item_summary=env.get(ENVVARS.GET_ITEM_SUMMARY, "True").lower() == "true",
            changelog_summary=env.get(ENVVARS.GET_CHANGELOG_SUMMARY, "True").lower()
            == "true",
        )
        self.prompts = prompts or Prompts(
            self.project.name,
            self.project.brief,
            self.project.changelog.notes,
        )
        self.output = output or Output(
            folder=env.get(ENVVARS.OUTPUT_FOLDER, "Releases"),
            name=self.project.name,
            version=self.project.version,
        )
        self.include_commits = (
            env.get(ENVVARS.INCLUDE_COMMITS, "True").lower() == "true"
        )


# pylint: disable=too-many-arguments
# pylint: disable=too-many-locals
def parse_project(
    name: str,
    version: str,
    brief: str,
    url: str,
    query: str,
    access_token: str,
    repo_name: str,
    branch: str = "",
    from_tag: str = "",
    to_tag: str = "",
    # Add these parameters
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> Project:
    """
    Extract platform information from the given URL and return a Project object.

    Args:
        url (str): The URL to analyze.
        branch (str): The branch to use for fetching commits.
        from_tag (str): The starting tag for fetching commits.
        to_tag (str): The ending tag for fetching commits.

    Returns:
        Project: An object containing the project name, URL, and platform information.

    Raises:
        ValueError: If the platform cannot be determined from the URL or if required information is missing.
    """
    parsed_url = urlparse(url)

    def get_github_info() -> Tuple[str, str, str]:
        parts = parsed_url.path.strip("/").split("/")
        if len(parts) < 2:
            raise ValueError(f"Invalid GitHub URL: {url}")
        return f"{parts[0]}/{parts[1]}", parts[0], "https://api.github.com"

    def get_azure_devops_info() -> Tuple[str, str, str]:
        parts = parsed_url.path.strip("/").split("/")
        if len(parts) < 2:
            raise ValueError(f"Invalid Azure DevOps URL: {url}")
        return unquote(parts[1]), parts[0], "https://dev.azure.com/"

    def get_old_azure_devops_info() -> Tuple[str, str, str]:
        parts = parsed_url.netloc.split(".")
        if len(parts) < 2:
            raise ValueError(f"Invalid Azure DevOps URL: {url}")
        organization = parts[0]
        project_parts = parsed_url.path.strip("/").split("/")
        if len(project_parts) < 1:
            raise ValueError(f"Invalid Azure DevOps URL: {url}")
        return (
            unquote(project_parts[0]),
            organization,
            f"https://{organization}.visualstudio.com",
        )

    if parsed_url.netloc == "github.com":
        project_name, org, base_url = get_github_info()
        platform = Platform.GITHUB
    elif (
        parsed_url.netloc.endswith("azure.com") and "dev.azure.com" in parsed_url.netloc
    ):
        project_name, org, base_url = get_azure_devops_info()
        platform = Platform.AZURE_DEVOPS
    elif parsed_url.netloc.endswith("visualstudio.com"):
        project_name, org, base_url = get_old_azure_devops_info()
        platform = Platform.AZURE_DEVOPS
    else:
        raise ValueError(f"Unable to determine platform from URL: {url}")

    platform_info = PlatformInfo(
        platform=platform,
        organization=org,
        base_url=base_url,
        query=query,
        access_token=access_token,
        repo_name=repo_name,
        branch=branch,
        from_tag=from_tag,
        to_tag=to_tag,
        # Add these parameters
        from_date=from_date,
        to_date=to_date,
    )

    return Project(
        name=name,
        ref=project_name,
        url=url,
        version=version,
        brief=brief,
        platform=platform_info,
        changelog=Notes(),
    )
