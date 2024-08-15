import csv
import time
import re

import undetected_chromedriver as uc
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

class DBScraper:
    def __init__(self):
        self._duns_bradstreet_url = "https://www.dnb.com/duns-number/lookup.html"
        self._driver = uc.Chrome()
        self._initialize()

    def _initialize(self):
        self._driver.get(self._duns_bradstreet_url)
        time.sleep(3) 

        # Close cookie pop-up
        try:
            cookie_close_button = self._driver.find_element(By.ID, "truste-consent-required")
            cookie_close_button.click()
        except NoSuchElementException:
            pass

    def execute_search(self, company_name, company_state, company_city="", company_zip="") -> list[dict]:

        self._reset_search_page()
        self._search_for_company(company_name, company_city, company_zip, company_state)

        duns_results = self._email_and_extract_duns_results()
        return duns_results

    """
    Navigate to or refresh the Duns Bradstreet search page
    """
    def _reset_search_page(self) -> None:
        self._driver.get(self._duns_bradstreet_url)

    """
    Fill in company details and submit search form
    """
    def _search_for_company(self, company_name: str, company_city: str, company_zip: str, company_state: str) -> None:
        search_type_selector = Select(self._driver.find_element(By.NAME, "primary-reason-dropdown-select-component"))
        search_type_selector.select_by_visible_text("My company")
        search_form_div = self._driver.find_element(By.CLASS_NAME, "container-search")  # business search container with inputs

        # Fill in business name
        search_form_div.find_element(By.NAME, "businessName").send_keys(company_name)  
        time.sleep(0.5)

        # Fill in business city
        search_form_div.find_element(By.NAME, "city").send_keys(company_city)
        time.sleep(0.5)

        # Fill in business zip
        # search_form_div.find_element(By.NAME, "zip").send_keys(zip_code)
        # time.sleep(0.5)

        # Pick business state from selector
        final_input_div = search_form_div.find_elements(By.CLASS_NAME, "search-form-row__row")[-2]
        state_selector = Select(final_input_div.find_element(By.TAG_NAME, "select"))
        state_selector.select_by_visible_text(company_state)

        # Submit search
        search_box = self._driver.find_element(By.ID, 'submit-search')
        search_box.click() 
        time.sleep(2)

    def _email_and_extract_duns_results(self) -> list[dict]:
        num_results_divs = len(self._driver.find_elements(By.CLASS_NAME, "search-results-card-container"))  # search results div
        
        all_duns_results = []
        # breakpoint()
        for result_index in range(num_results_divs):
            all_duns_results.append(self._email_and_extract_duns_result(result_index))

        return all_duns_results

    # Process an individual search result
    def _email_and_extract_duns_result(self, result_index: int) -> None:

        result_div = self._find_and_scroll_to_result_div(result_index)
        duns_results = self._extract_company_info(result_div)
        self._request_email_for_result(result_div)
        self._close_success_modal()
        return duns_results


    """
    Find nth results div and scroll it into view
    Return: results div
    """
    def _find_and_scroll_to_result_div(self, result_index: int) -> WebElement:
        results_div =self._driver.find_elements(By.CLASS_NAME, "search-results-card-container")[result_index]  # Find the nth result div
        time.sleep(0.5)
        self._driver.execute_script("arguments[0].scrollIntoView(true);", results_div)  # Scroll results div into view
        return results_div

    def _request_email_for_result(self, result_div: WebElement):
        email_duns_button = result_div.find_element(By.XPATH, ".//a[contains(text(), 'Email D-U-N-S')]")  # Find 'Email D-U-N-S number' element'
        email_duns_button.click()
        time.sleep(1)

        email_request_div = self._driver.find_element(By.CLASS_NAME, "requestform")
        
        # Fill in the email form fields 
        email_request_div.find_element(By.NAME, 'FIRST_NAME').send_keys('Manipa') 
        time.sleep(0.5)
        email_request_div.find_element(By.NAME, 'LAST_NAME').send_keys('Jokosa')
        time.sleep(0.5)
        email_request_div.find_element(By.NAME, 'EMAIL_ADDRESS').send_keys('thomasapyncheon@gmail.com') 
        time.sleep(0.5)

        # Submit email request form
        final_submit_button = email_request_div.find_element(By.CLASS_NAME, "requestform__submit")
        self._driver.execute_script("arguments[0].scrollIntoView(true);", final_submit_button)
        final_submit_button.click()
        time.sleep(5)

        
    """
    Close modal telling us an email was sent
    """
    def _close_success_modal(self) -> None:
        success_modal = WebDriverWait(self._driver, 60).until(EC.element_to_be_clickable((By.CLASS_NAME, 'sprite--close')))
        self._driver.execute_script("arguments[0].scrollIntoView(true);", success_modal)
        success_modal.click()
        time.sleep(2)

    """
    Extract company data from result div
    Return: dict containing company data
    """
    def _extract_company_info(self, result_div: WebElement) -> dict:
        company_name = result_div.find_element(By.CLASS_NAME, "name").text
        company_address = result_div.find_element(By.CLASS_NAME, "address").text
        company_phone = result_div.find_element(By.CLASS_NAME, "phone").text
        company_type = result_div.find_element(By.CLASS_NAME, "type").text
        company_status = result_div.find_element(By.CLASS_NAME, "status").text

        return {
            "duns_name": company_name,
            "duns_address": company_address,
            "duns_phone": company_phone,
            "duns_type": company_type,
            "company_status": company_status
        }


