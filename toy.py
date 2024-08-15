import csv
import re
import time

from duns_bradstreet_scraper.duns_bradstreet_scraper import DBScraper


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

scraper = DBScraper()

with open("toy_inputs/nlrb_nxgen_dataset_2.csv", "r") as infile:
    reader = csv.DictReader(infile)
    union_elections = [row for row in reader]

with open("toy_inputs/state_identifiers.csv", "r") as infile:
    reader = csv.DictReader(infile)
    state_initial_map = {row["state_abbr"]: row["state_name"] for row in reader}


with open("toy_outputs/duns_company_data.csv", "r") as infile:
    reader = csv.DictReader(infile)
    all_duns_results = [row for row in reader]


# Note: Code below might search for a company multiple times. Fix that
for election_index, union_election in enumerate(union_elections):
    if union_election.get("scraped") in [1,2,3]:
        continue

    company_name = clean_employer_name(union_election["employer_name"])
    company_city = union_election["emp_1_city"]
    company_state = state_initial_map.get(union_election["emp_1_state"])
    # company_zip = union_election["emp_1_zip"]  # should we really use this?

    case_number = union_election["case_number"]

    # Failed to clean company name
    if not company_name:
        union_elections[election_index]["scraped"] = 2
        continue

    if not company_state:
        union_elections[election_index]["scraped"] = 3
        continue

    print(election_index, case_number, company_name)

    duns_results = scraper.execute_search(
            company_name=company_name,
            company_state=company_state,
            company_city=company_city
            # company_zip=company_zip,
            )

    # Add NLRB election case number
    duns_results = [result | {"case_number": case_number} for result in duns_results]

    # Mark election as scraped
    union_elections[election_index]["scraped"] = 1

    time.sleep(2)

    all_duns_results.extend(duns_results)

    if election_index % 10 == 1:
        with open("toy_outputs/duns_company_data.csv", "w+") as outfile:
            writer = csv.DictWriter(outfile, fieldnames=all_duns_results[0].keys())
            writer.writeheader()
            writer.writerows(all_duns_results)

        with open("toy_inputs/nlrb_nxgen_dataset_2.csv", "w+") as outfile:
            writer = csv.DictWriter(outfile, fieldnames = union_elections[0].keys())
            writer.writeheader()
            writer.writerows(union_elections)



