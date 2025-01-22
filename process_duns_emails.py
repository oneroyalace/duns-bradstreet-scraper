import csv
import email
import mailbox
import re
from email.policy import default

import arrow
import html2text
from tqdm import tqdm

def check_for_email_log_match(log_entry, email):
    email_company = email["company_name"].lower()
    log_company = log_entry["duns_name"].lower()

    return email_company == log_company


"""
Check whether any email in the email buffer matches the current log entry
"""
def check_for_buffer_match(log_entry: dict, email_buffer: list[dict]):
    # print("log entry", log_entry)
    # print("email buffer", email_buffer)
    for buffer_ind, buffer_entry in enumerate(email_buffer):
       if check_for_email_log_match(log_entry, buffer_entry):
           return buffer_ind, buffer_entry
    return None
            
with open("toy_outputs/duns_company_data.csv", "r") as infile:
    reader = csv.DictReader(infile)
    duns_log = [row for row in reader]

with open("dnb_emails.csv", "r") as infile:
    reader = csv.DictReader(infile)
    emails = [row for row in reader]


# If current email doesn' match log entry
# keep advancing emails + adding emails to eamil buffer until find one matching log entry
# advance log entry, searching email buffer for matches. if no buffer matches, advance emails. 
# Always check eamil buffer unless it's empty


email_index = 0
log_index = 0
email_buffer = []
# while log_index < len(duns_log):
while email_index < len(emails):
    print(email_index, log_index)
    email = emails[email_index]
    log_entry = duns_log[log_index]
    
    if not eval(log_entry["email_success"]):
        log_index += 1
        continue

    # If email at current email index matches log entry at current log index
    if check_for_email_log_match(log_entry, email) == True:
        log_entry["duns_number"] = emails[email_index]["duns_code"]
        email_index += 1
        log_index += 1
        print(f"Match email {email_index} to log entry {log_index}. Company: {log_entry['duns_name']}")
        continue

    if len(email_buffer) > 0:
        buffer_match = check_for_buffer_match(log_entry, email_buffer)
        if buffer_match is not None:
            buffer_match_index = buffer_match[0]
            matched_email = buffer_match[1]

            log_entry["duns_number"] = matched_email["duns_code"]
            email_buffer.pop(buffer_match_index)
            log_index += 1
            continue
            # don't advance email index, since we drew from the buffer

    email_buffer.append(email)
    print(f"Appending email {email_index} to buffer")
    email_index += 1

