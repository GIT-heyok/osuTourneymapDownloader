import json
import os
import re
import sys
import time
from math import ceil
import getpass

import requests
from loguru import logger
from tqdm import tqdm

DOWNLOAD_PATH = os.curdir+"/Downloads"
# Windows
if sys.platform.startswith("win32"):
    USERPROFILE = os.getenv("USERPROFILE")
# Linux or MacOS
else:
    USERPROFILE = os.getenv("HOME")
HOME_DIR = os.path.join(USERPROFILE, ".osu-beatmap-downloader")
CREDS_FILEPATH = os.path.join(HOME_DIR, "credentials.json")
LOGS_FILEPATH = os.path.join(HOME_DIR, "downloader.log")
ILLEGAL_CHARS = re.compile(r"[\<\>:\"\/\\\|\?*]")

FORMAT_TIME = "<cyan>{time:YYYY-MM-DD HH:mm:ss}</cyan>"
FORMAT_LEVEL = "<level>{level: <8}</level>"
FORMAT_MESSAGE = "<level>{message}</level>"
LOGGER_CONFIG = {
    "handlers": [
        {
            "sink": sys.stdout,
            "format": " | ".join((FORMAT_TIME, FORMAT_LEVEL, FORMAT_MESSAGE)),
        },
        {
            "sink": LOGS_FILEPATH,
            "format": " | ".join((FORMAT_TIME, FORMAT_LEVEL, FORMAT_MESSAGE)),
        },
    ]
}
logger.configure(**LOGGER_CONFIG)

OSU_URL = "https://osu.ppy.sh/home"
OSU_SESSION_URL = "https://osu.ppy.sh/session"
OSU_SEARCH_URL = "https://osu.ppy.sh/beatmapsets/search"
class CredentialHelper:
    def __init__(self):
        self.credentials = {}

    def ask_credentials(self):
        self.credentials["username"] = input('Please enter your osu! username: ')
        self.credentials["password"] = input('Please enter your osu! password: ')
        if input("Do you want to save the osu! credentials at " + CREDS_FILEPATH + "? (y/n): ").lower() == "y":
            self.save_credentials()

    def load_credentials(self):
        try:
            with open(CREDS_FILEPATH, "r") as cred_file:
                self.credentials = json.load(cred_file)
        except FileNotFoundError:
            logger.info(f"File {CREDS_FILEPATH} not found")
            self.ask_credentials()

    def save_credentials(self):
        try:
            with open(CREDS_FILEPATH, "w") as cred_file:
                json.dump(self.credentials, cred_file, indent=2)
        except IOError:
            logger.error(f"Error writing {CREDS_FILEPATH}")

    def delete_credentials(self):
        try:
            if os.path.isfile(CREDS_FILEPATH):
                os.remove(CREDS_FILEPATH)
                logger.success(f"Successfully deleted {CREDS_FILEPATH}")
        except IOError:
            logger.error(f"Error deleting {CREDS_FILEPATH}")


class BeatmapSet:
    def __init__(self, data):
        self.set_id = data["id"]
        self.title = data["title"]
        self.artist = data["artist"]
        self.url = f"https://osu.ppy.sh/beatmapsets/{self.set_id}"

    def __str__(self):
        string = f"{self.set_id} {self.artist} - {self.title}"
        return ILLEGAL_CHARS.sub("_", string)


class Downloader:
    def __init__(self, limit, no_video):
        self.beatmapsets = set()
        self.limit = limit
        self.no_video = no_video
        self.cred_helper = CredentialHelper()
        self.cred_helper.load_credentials()
        self.session = requests.Session()
        self.login()
        self.scrape_beatmapsets()
        self.remove_existing_beatmapsets()

    def get_token(self):
        # access the osu! homepage
        homepage = self.session.get(OSU_URL)
        # extract the CSRF token sitting in one of the <meta> tags
        regex = re.compile(r".*?csrf-token.*?content=\"(.*?)\">", re.DOTALL)
        match = regex.match(homepage.text)
        csrf_token = match.group(1)
        return csrf_token

    def login(self):
        logger.info(" made by hyeok2044 ")
        logger.info(" DOWNLOADER STARTED ".center(50, "#"))
        data = self.cred_helper.credentials
        data["_token"] = self.get_token()
        headers = {"referer": OSU_URL}
        res = self.session.post(OSU_SESSION_URL, data=data, headers=headers)
        if res.status_code != requests.codes.ok:
            logger.error("Login failed")
            if input("Do you want to delete the osu! credentials at " + CREDS_FILEPATH + "? (y/n): ").lower() == "y":
                self.cred_helper.delete_credentials()
            sys.exit(1)
        logger.success("Login successful")

    def scrape_beatmapsets(self):
        fav_count = sys.maxsize
        num_beatmapsets = 0
        logger.info("Scraping beatmapsets!")
        logger.info("Paste the beatmap ID to download one beatmap file or")
        logger.info("Search like how you do it in osu")
        logger.info("Type -1 at the last line to finish searching.")
        s = input()
        while s != "-1":
            if s == "":
                s = input()
                continue
            params = {
                "m": 0,
                "q": s,
                "s": "any"
            }
            response = self.session.get(OSU_SEARCH_URL, params=params)
            data = response.json()
            if s.isnumeric():
                chkIfExists = False
                for bmset in data["beatmapsets"]:
                    if not chkIfExists:
                        for oneMap in bmset["beatmaps"]:
                            if oneMap["id"] == int(s):
                                self.beatmapsets.add(BeatmapSet(bmset))
                                chkIfExists = True
                                break
                if not chkIfExists:
                    logger.error("unable to find the beatmapset with ID: " + s)
            else:
                self.beatmapsets.update(
                    (BeatmapSet(bmset) for bmset in data["beatmapsets"])
                )

            num_beatmapsets = len(self.beatmapsets)
            s = input()
        logger.success(f"Scraped {num_beatmapsets} beatmapsets.")

    def remove_existing_beatmapsets(self):
        filtered_set = set()
        for beatmapset in self.beatmapsets:
            dir_path = os.path.join(DOWNLOAD_PATH, str(beatmapset))
            file_path = dir_path + ".osz"
            if os.path.isdir(dir_path) or os.path.isfile(file_path):
                logger.info(f"Beatmapset already downloaded: {beatmapset}")
                continue
            filtered_set.add(beatmapset)
        self.beatmapsets = filtered_set

    def download_beatmapset_file(self, beatmapset):
        logger.info(f"Downloading beatmapset: {beatmapset}")
        headers = {"referer": beatmapset.url}
        download_url = beatmapset.url + "/download"
        if self.no_video:
            download_url += "?noVideo=1"
        response = self.session.get(download_url, headers=headers, stream=True)
        if response.status_code == requests.codes.ok:
            logger.success(f"{response.status_code} - Download successful")
            self.write_beatmapset_file(str(beatmapset), response)
            return True
        else:
            logger.warning(f"{response.status_code} - Download failed")
            return False

    def write_beatmapset_file(self, filename, data):
        file_path = os.path.join(DOWNLOAD_PATH, f"{filename}.osz")
        logger.info(f"Writing file: {file_path}")
        file_size = int(data.headers['content-length'])
        downloaded = 0
        with open(file_path, "wb") as outfile:
            for chunk in tqdm(data.iter_content(chunk_size=4096), total=ceil(file_size/4096)):
                downloaded += outfile.write(chunk)
        logger.success("File write successful")

    def run(self):
        logger.info("List of beatmaps to be downloaded:")
        for beatmapset in self.beatmapsets:
            logger.info(beatmapset)
        tries = 0
        while self.beatmapsets:
            next_set = self.beatmapsets.pop()
            download_success = self.download_beatmapset_file(next_set)
            if download_success:
                tries = 0
                time.sleep(2)
            else:
                self.beatmapsets.add(next_set)
                tries += 1
                if tries > 4:
                    logger.error("Failed 5 times in a row")
                    logger.info("Website download limit reached")
                    logger.info("Try again later")
                    logger.info(" DOWNLOADER TERMINATED ".center(50, "#") + "\n")
                    sys.exit()
        logger.info(" DOWNLOADER FINISHED ".center(50, "#") + "\n")


def main():
    crH = CredentialHelper()

    if not os.path.exists(DOWNLOAD_PATH):
        os.makedirs(DOWNLOAD_PATH)

    try:
        with open(CREDS_FILEPATH, "r") as cred_file:
            print("loaded with username : ", json.load(cred_file)['username'])
    except FileNotFoundError:
        logger.info(f"File {CREDS_FILEPATH} not found")
        crH.ask_credentials()

    dl = Downloader(10, 1)
    dl.run()


if __name__ == "__main__":
    main()
