import csv
import logging
import math
import random
import re
import time
from datetime import timedelta
from enum import Enum

import arrow
# import pyautogui

from duns_bradstreet_scraper.duns_bradstreet_scraper import DBScraper, DNBServerException, DNBRejectionException


def clean_employer_name(emp_name):
    re_dba = re.compile(r"(.*)d[^a-z]?b[^a-z]?a(.*)", re.IGNORECASE)
    if re.search(re_dba, emp_name):
        emp_name = re_dba.search(emp_name).groups()[1]

    

    partitions = [re.compile(r",? inc\.?", re.IGNORECASE), # inc
                  re.compile(r",? ?l\.?l\.?c\.?", re.IGNORECASE), # llc
                  re.compile(r"a subsidiary", re.IGNORECASE),
                  re.compile(r"an affiliate", re.IGNORECASE),
                  re.compile(r"a division", re.IGNORECASE),
                  re.compile(r" -|- ", re.IGNORECASE), # space dash or dash space
                  re.compile(r"/", re.IGNORECASE),

                  # I think DUNS shoudl be okay with "corp", "corporation", "etc.". They fuzzy search
                  
                  # re.compile("co\.", re.IGNORECASE),  # co. 
                  # re.compile(r"corporation", re.IGNORECASE),  # corporation
                  # re.compile("corp\.", re.IGNORECASE),  # corp.
                  # re.compile(r"company", re.IGNORECASE),  # company
                  ]

    for partition_re in partitions:
        match = partition_re.search(emp_name)
        if match:
            emp_name = emp_name[:match.start()]

    replacements = [
            re.compile("-TV", re.IGNORECASE),
            re.compile("ltd", re.IGNORECASE),
            re.compile(r"\(.*?\)")  # text in parentheses
            ]

    for replace_reg in replacements:
        emp_name = replace_reg.sub("", emp_name)

    # emp_name = emp_name.replace("&", "%26")

    emp_name = emp_name.strip()
    return emp_name

def truncate_employer_name(emp_name: str, char_limit: int) -> str:
    words = emp_name.split(" ")
    truncated_name = ""

    if len(emp_name) <= char_limit:
        return emp_name

    for word in words:
        if (len(truncated_name) + len(word)) + 1 > char_limit:  # If adding the next word would put the name over the character limit...
            break
        truncated_name = " ".join([truncated_name, word])  # Add next word to name
    return truncated_name

"""
Use pyautogui to switch to a new ProtonVPN server and hopefully juke anti-scraping tech
"""
def rotate_vpn_server():
    open_protonvpn()
    connect_to_new_server()
    switch_focus_back_to_chrome()


"""
Use pyautogui to open the ProtonVPN app
"""
def open_protonvpn() -> None:
    pyautogui.hotkey("command", "space")
    time.sleep(0.2)
    pyautogui.write("Proton")
    pyautogui.press("enter")

"""
Use pyautogui to connect to a new US-based ProtonVPN server
"""
def connect_to_new_server() -> None:
    pyautogui.moveTo(263, 365)  # Hover over US server profile
    time.sleep(1)
    pyautogui.click()  # Click "connnect" for US server profile

    print("Sleeping for 15 seconds while connecting to new server")
    time.sleep(15)

def switch_focus_back_to_chrome() -> None:
    pyautogui.hotkey("command", "space")
    time.sleep(0.2)
    pyautogui.write("chrome")
    pyautogui.press("enter")

def set_up_logger(logfile):
    # Create a custom logger
    logger = logging.getLogger("toy_do_over_log")

    logger.setLevel(logging.INFO)  
    console_handler = logging.StreamHandler()  # Handler for stdout
    file_handler = logging.FileHandler(logfile)  # Handler for file output

    console_handler.setLevel(logging.INFO)
    file_handler.setLevel(logging.INFO)

    formatter = logging.Formatter(fmt='%(asctime)s %(levelname)s:  %(message)s', datefmt="%Y-%m-%d %H:%M:%S")
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger


with open("toy_inputs/duns_to_scrape_take_2.csv", "r") as infile:
    reader = csv.DictReader(infile)
    cases_for_scraping = [row for row in reader]

with open("toy_outputs/duns_log_take_2.csv", "r") as infile:
    reader = csv.DictReader(infile)
    all_duns_results = [row for row in reader]

with open("toy_inputs/state_identifiers.csv", "r") as infile:
    reader = csv.DictReader(infile)
    state_initial_map = {row["state_abbr"]: row["state_name"] for row in reader}

with open("toy_outputs/already_scraped.csv") as infile:
    reader = csv.DictReader(infile)
    already_scraped = [(row["company_name"], row["city"], row["state"]) for row in reader]

logger = set_up_logger(logfile = "toy_outputs/doover.log")

scraper = DBScraper(logger=logger)
# rotate_vpn_server()
scrapes_until_server_switch = 10

class ScrapeStatus(Enum):
    SUCCESSFULLY_SCRAPED    = 1
    NO_COMPANY_GEOGRAPHY    = 3
    DNB_SERVER_EXCEPTION    = 4
    MATCHES_EXISTING_SCRAPE = 5


"""
Toss old exceptions out of the exception buffer
"""
def flush_exception_buffer(buffer: list[arrow.arrow.Arrow]) -> list[arrow.arrow.Arrow]:
    ten_minutes_ago = arrow.now() - timedelta(minutes=10)
    buffer = [e for e in buffer if e < ten_minutes_ago]
    return buffer

recent_exception_buffer = []
# Note: Code below might search for a company multiple times. Fix that
dnb_searches_since_last_sleep = 0
for case_ind, case_details in enumerate(cases_for_scraping):
    if case_details["scrape_status"] and \
            int(case_details["scrape_status"]) in [ScrapeStatus.SUCCESSFULLY_SCRAPED.value, ScrapeStatus.NO_COMPANY_GEOGRAPHY.value, ScrapeStatus.MATCHES_EXISTING_SCRAPE]:
        continue

    case_number = case_details["case_number"]
    company_name = case_details["company_name"]
    company_city = case_details["emp_1_city"]
    company_state = state_initial_map.get(case_details["emp_1_state"])

    clean_name_1 = case_details["clean_name_1"]
    clean_name_2 = case_details["clean_name_2"]

    recent_exception_buffer = flush_exception_buffer(recent_exception_buffer)

    # if len(recent_exception_buffer) >= 5: 
    #     logger.debug(f"\n*****Seen 5 exceptions in the last ten minutes. Sleeping for 3 minutes. ")
    #     time.sleep(180)
    #     scrapes_until_server_switch = 0
    # elif dnb_searches_since_last_sleep >= 7:
    #     dnb_searches_since_last_sleep = 0
    #     logger.info("\n_____Sleeping for ~45 seconds______")
    #     time.sleep(44)

    if not company_state:
        cases_for_scraping[case_ind]["scrape_status"] = ScrapeStatus.NO_COMPANY_GEOGRAPHY.value
        logger.debug(f"\n\n\n*****Skipping case #{case_ind+1}/{len(cases_for_scraping)} ({case_number}: {company_name})*****. No company city/state available")
        continue

    new_vpn_server = False

    if scrapes_until_server_switch <= 0:
        # rotate_vpn_server()
        scrapes_until_server_switch = max(math.floor(random.gauss(13,5)), 3)
        new_vpn_server = True

    logger.info(f"\n\n\n*****Processing case #{case_ind+1}/{len(cases_for_scraping)} ({case_number}: {company_name})*****")
    logger.info(f"Scrapes until server switch: {scrapes_until_server_switch}")


    try:
        duns_results_name_1 = []
        duns_results_name_2 = []

        logger.info("sleep 20 to check sensitivity")
        if (clean_name_1, company_city, company_state) in already_scraped:
            logger.info(f"Have already scapped DNB for details matching clean name 1: '{clean_name_1}' in {(company_city, company_state)}")
            cases_for_scraping[case_ind]["scrape_status"] = ScrapeStatus.MATCHES_EXISTING_SCRAPE.value
            continue
        else:
            time.sleep(20)
            logger.info(f"Scraping for company w/ following details:")
            logger.info(f"Clean name (1): {clean_name_1}")
            logger.info(f"Company city: {company_city}")
            logger.info(f"Company state: {company_state}")

            dnb_searches_since_last_sleep += 1

            duns_results_name_1 = scraper.execute_search(
                    company_name=clean_name_1,
                    company_state=company_state,
                    company_city=company_city,
                    new_vpn_server=new_vpn_server
                )
            already_scraped.append((clean_name_1, company_city, company_state))

        if clean_name_2 and (clean_name_2, company_city, company_state) in already_scraped :
            logger.info(f"Have already scapped DNB for details matching clean name 2: '{clean_name_2}' in {(company_city, company_state)}")
            cases_for_scraping[case_ind]["scrape_status"] = ScrapeStatus.MATCHES_EXISTING_SCRAPE.value
            continue
        if clean_name_2 and (clean_name_2, company_city, company_state) not in already_scraped :
            if not any([result["email_success"] for result in duns_results_name_1]):
                logger.info(f"Scraping for company w/ following details:")
                logger.info(f"Clean name (2): {clean_name_2}")
                logger.info(f"Company city: {company_city}")
                logger.info(f"Company state: {company_state}")

                dnb_searches_since_last_sleep += 1

                duns_results_name_2 = scraper.execute_search(
                        company_name=clean_name_2,
                        company_state=company_state,
                        company_city=company_city,
                        new_vpn_server=new_vpn_server
                )
                already_scraped.append((clean_name_2, company_city, company_state))

    except DNBServerException:
        logging.error("DNB Server error!!!!!!")
        cases_for_scraping[case_ind]["scrape_status"] = ScrapeStatus.DNB_SERVER_EXCEPTION.value
        recent_exception_buffer.append(arrow.now())
        scrapes_until_server_switch -= 15 
        continue
    except DNBRejectionException:
        logging.error("DNB is totally blocking access. Sleeping for 2 minutes, then switching VPN servers")
        cases_for_scraping[case_ind]["scrape_status"] = ScrapeStatus.DNB_SERVER_EXCEPTION.value
        time.sleep(120)
        scrapes_until_server_switch = 0
        continue



    duns_results = duns_results_name_2 or duns_results_name_1  # If we made a second search, use its results. Else use first search's. 
    # Add NLRB election case number
    duns_results = [result | {"case_number": case_number} for result in duns_results]

    if cases_for_scraping[case_ind]["scrape_status"] == ScrapeStatus.DNB_SERVER_EXCEPTION.value:
        duns_results = [ result | {"from_retry": True} for result in duns_results]
    else:
        duns_results = [ result | {"from_retry": False} for result in duns_results]

    # Mark election as scraped
    cases_for_scraping[case_ind]["scrape_status"] = ScrapeStatus.SUCCESSFULLY_SCRAPED.value

    time.sleep(2)
    scrapes_until_server_switch -= 1

    all_duns_results.extend(duns_results)

    # if case_ind % 5 == 1:
    logger.info("((((((((Saving progress to disk))))))")
    with open("toy_outputs/duns_log_take_2.csv", "w+", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=all_duns_results[0].keys())
        writer.writeheader()
        writer.writerows(all_duns_results)

    with open("toy_inputs/duns_to_scrape_take_2.csv", "w+", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames = cases_for_scraping[0].keys())
        writer.writeheader()
        writer.writerows(cases_for_scraping)

    already_scraped_rows = [{"company_name": row[0], "city": row[1], "state": row[2]} for row in already_scraped]
    with open("toy_outputs/already_scraped.csv", "w+", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames = already_scraped_rows[0].keys())
        writer.writeheader()
        writer.writerows(already_scraped_rows)

