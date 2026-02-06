"""
Guide:
1. create a Dropbox app on web.
2. enable "files.content.write" and any needed scopes.
3. set redirect type: "Allow implicit grant" OFF; use code flow.
4. run this script locally (not on server without browser).
"""

from dropbox.oauth import DropboxOAuth2FlowNoRedirect

from pi_rec.config import get_settings

settings = get_settings()

APP_KEY = settings.dropbox.app_key.get_secret_value()
APP_SECRET = settings.dropbox.app_secret.get_secret_value()

if __name__ == "__main__":
    flow = DropboxOAuth2FlowNoRedirect(
        consumer_key=APP_KEY,
        consumer_secret=APP_SECRET,
        # use_pkce=True,
        token_access_type="offline",  # requests refresh token # noqa: S106
        scope=[
            "account_info.read",
            "files.content.write",
            "files.content.read",
            "files.metadata.read",
        ],
    )

    auth_url = flow.start()
    print("1. Visit:", auth_url)
    print("2. Click Allow, copy the authorization code.")
    code = input("Authorization code: ").strip()

    oauth_result = flow.finish(code)

    print("\nSave this value to config.yaml [dropbox.refresh_token]:")
    print(oauth_result.refresh_token)
