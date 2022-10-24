import requests
import os

def get_env_var(env_key: str):
    gpg_key_id = os.environ[env_key]
    if gpg_key_id is None:
        raise Exception(
            f"Could not find {env_key} in your environment. Add it and run this action again"
        )
    return gpg_key_id

base_provider_file_name = "terraform-provider-google"
org_name = "candid-health"

config = {
    "version": get_env_var(env_key="REF_NAME"),
    "provider_name": "google",
    "github_repo_url": f"https://github.com/candid-health/{base_provider_file_name}",
    "registry_name": "private",
    "base_api_url": "https://app.terraform.io/api/v2",
    "org_name": org_name,
    "namespace": org_name,
}

print('======== VERSION ========')
print(config['version'])


def generate_file_name(version: str, platform: str, arch: str):
    return f"{base_provider_file_name}_{version}_{platform}_{arch}.zip"


shasum_file = f"{base_provider_file_name}_{config['version']}_SHA256SUMS"
shasum_sig_file = f"{base_provider_file_name}_{config['version']}_SHA256SUMS.sig"
manifest_file = f"{base_provider_file_name}_{config['version']}_manifest.json"

# List of assets to download
# this list is expanded by code further down
assets_to_download = [manifest_file, shasum_file, shasum_sig_file]

operating_systems = ["darwin", "linux"]
architectures = ["arm64", "amd64"]

# list of all platform objects
# os and arch
platforms = []

for operating_system in operating_systems:
    for arch in architectures:
        platforms.append({"os": operating_system, "arch": arch})

for platform in platforms:
    file_name = generate_file_name(
        version=config["version"], platform=platform["os"], arch=platform["arch"]
    )
    assets_to_download.append(file_name)


def get_auth_headers():
    admin_token = get_env_var(env_key="TF_ADMIN_TOKEN")
    return {"Authorization": f"Bearer {admin_token}"}


def get_content_type_headers():
    return {"Content-Type": "application/vnd.api+json"}


def upload_asset_to_tf_provided_upload_url(file: str, url: str):
    print(f"Uploading file: {file} to url: {url}...")
    f = open(file, 'rb')
    files = {
        'file': f
    }
    try:
        file_upload_res = requests.put(url, files=files)
        print('file upload res:')
        print(file_upload_res)
        if file_upload_res.status_code is not 200:
            print(file_upload_res.json())
            raise Exception(f"Could not upload file: {file} to url: {url}")
    finally:
        f.close()

def does_provider_version_exists():
    url = f"{config['base_api_url']}/organizations/{config['org_name']}/registry-providers/{config['registry_name']}/{config['namespace']}/{config['provider_name']}/versions/{config['version']}"
    headers = dict()
    headers.update(get_auth_headers())
    check_for_provider_res = requests.get(url, headers=headers)
    if check_for_provider_res.status_code is 200:
        return True
    else:
        return False


# https://www.terraform.io/cloud-docs/api-docs/private-registry/provider-versions-platforms#create-a-provider-version
def create_new_provider_version():
    url = f"{config['base_api_url']}/organizations/{config['org_name']}/registry-providers/{config['registry_name']}/{config['namespace']}/{config['provider_name']}/versions"
    print(url)
    post_params = {
        "data": {
            "type": "registry-provider-versions",
            "attributes": {
                "version": config["version"],
                "key-id": get_env_var(env_key="GPG_KEY_ID"),
                "protocols": ["5.0"],
            },
        }
    }
    headers = dict()
    headers.update(get_auth_headers())
    headers.update(get_content_type_headers())
    print(headers)
    print(post_params)
    post_res = requests.post(url, headers=headers, json=post_params)
    print(post_res)
    if post_res.status_code != 201:
        print(post_res.json())
        raise Exception(f"Error creating new version: {url}")
    
    json_res = post_res.json()

    # Upload shasum files to provided urls
    upload_asset_to_tf_provided_upload_url(file=shasum_file, url=json_res['data']['links']['shasums-upload'])
    upload_asset_to_tf_provided_upload_url(file=shasum_sig_file, url=json_res['data']['links']['shasums-sig-upload'])


# https://www.terraform.io/cloud-docs/api-docs/private-registry/provider-versions-platforms#create-a-provider-platform
def create_new_platform(filename: str, shasum: str, arch: str, os: str) -> dict:
    headers = dict()
    headers.update(get_auth_headers())
    headers.update(get_content_type_headers())

    post_params = {
        "data": {
            "type": "registry-provider-version-platforms",
            "attributes": {
                "os": os,
                "arch": arch,
                "shasum": shasum,
                "filename": filename,
            },
        }
    }
    url = f"{config['base_api_url']}/organizations/{config['org_name']}/registry-providers/{config['registry_name']}/{config['namespace']}/{config['provider_name']}/versions/{config['version']}/platforms"
    print(f"Create new platform... {url}")
    new_platform_res = requests.post(url, headers=headers, json=post_params)
    if new_platform_res.status_code != 201:
        print(new_platform_res.text)
        raise Exception(f"Error creating platform: {url}")
    print("Created platform successfully! os: {os}, arch: {arch}")
    res_json = new_platform_res.json()
    print(res_json)
    result = {
        "filename": filename,
        "upload_url": res_json["data"]["links"]["provider-binary-upload"]
    }
    return result


def parse_shasum_file():
    # read shasum file and parse into useful data structure
    f = open(shasum_file, "r")
    shasum_split_lines = f.read().splitlines()
    shasum_dict = {}
    for shasum_line in shasum_split_lines:
        split_line = shasum_line.split("  ")
        this_shasum = split_line[0]
        this_filename = split_line[1]
        shasum_dict[this_filename] = this_shasum
    return shasum_dict


def create_all_platforms():
    # generate data structure with all relevant metadata
    all_platforms_generated_list = []
    shasum_dict = parse_shasum_file()

    for operating_system in operating_systems:
        for arch in architectures:
            filename = generate_file_name(
                version=config["version"], platform=operating_system, arch=arch
            )
            all_platforms_generated_list.append(
                {
                    "filename": filename,
                    "shasum": shasum_dict[filename],
                    "arch": arch,
                    "os": operating_system,
                }
            )
    all_platform_links = list()
    for platform in all_platforms_generated_list:
        all_platform_links.append(create_new_platform(
            filename=platform["filename"],
            shasum=platform["shasum"],
            arch=platform["arch"],
            os=platform["os"],
        ))

    for entry in all_platform_links:
        # Upload all platform resources
        upload_asset_to_tf_provided_upload_url(file=entry['filename'], url=entry['upload_url'])


def download_all_assets_from_github_release():
    for file in assets_to_download:
        download_url = (
            f"{config['github_repo_url']}/releases/download/v{config['version']}/{file}"
        )
        print(f"download file... {file}")
        file_res = requests.get(download_url)

        if file_res.status_code != 200:
            raise Exception(f"Error pulling resource: {download_url}")

        # Save all files locally
        with open(file, "w") as f:
            f.write(file_res.text)


def do_full_deploy():
    # Assuming deploy of package has completed to Github Releases

    # Download all assets from github
    download_all_assets_from_github_release()

    # Check if provider already exists
    if does_provider_version_exists() is False:
        # If not, create it
        create_new_provider_version()

    # Create platform and upload assets for each build type
    create_all_platforms()


do_full_deploy()
