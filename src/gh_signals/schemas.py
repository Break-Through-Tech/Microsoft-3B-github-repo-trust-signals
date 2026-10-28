"""Typed models for the parts of the GitHub API we consume."""

from pydantic import BaseModel


class Repo(BaseModel):
    """The repository fields we use as trust signals, named exactly as the GitHub API names them."""

    full_name: str
    stargazers_count: int
    forks_count: int


class Contributor(BaseModel):
    """One entry from the repository contributors endpoint.

    ``contributions`` is the number of commits on the default branch. Anonymous
    contributors are not represented, because they have no login to follow across repositories.
    """

    login: str
    contributions: int
    type: str = "User"
