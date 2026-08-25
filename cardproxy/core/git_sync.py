from git import Repo


def sync_with_remote(
    repo_path: str, verbose: bool = True, interactive: bool = True
) -> tuple:
    """
    Synchronize local branch with remote.

    When ``interactive`` is False, do not prompt and do not pull — just report
    the status and return the current local commit. The GUI drives its own
    update prompt at startup and passes ``interactive=False`` afterwards so the
    render worker never blocks on ``input()``.
    """

    repo = Repo(repo_path)
    assert not repo.bare

    active_branch = repo.active_branch
    origin = repo.remotes.origin
    origin.fetch(verbose=verbose)

    remote_commit = repo.commit(f"origin/{active_branch.name}")
    local_commit = repo.commit(active_branch.name)
    num_commits_behind = len(
        [*repo.iter_commits(f"{local_commit.hexsha}..{remote_commit.hexsha}")]
    )

    print(
        f"[CARD-PROXY-PRINTER] Local branch is {num_commits_behind} commit(s) behind remote branch."
    )

    pull_response = "no"
    if num_commits_behind > 0 and interactive:
        while True:
            pull_response = input(
                "[CARD-PROXY-PRINTER] Might want to fetch all latest changes. Enter yes/no to continue: "
            )
            if pull_response == "yes" or pull_response == "no":
                break

        if pull_response == "yes":
            print("[CARD-PROXY-PRINTER] Pulling changes...")
            origin.pull(verbose=verbose)
            print("[CARD-PROXY-PRINTER] Local branch code is now up to date.")
        else:
            print("[CARD-PROXY-PRINTER] Skipping code actualization.")
    else:
        print("[CARD-PROXY-PRINTER] Skipping code actualization.")

    return repo.commit(active_branch.name), pull_response == "yes"
