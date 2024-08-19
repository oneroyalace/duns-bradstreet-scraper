import csv
import logging
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
        self._logger = None
        self._driver = None
        self._initialize()

    def _initialize(self):
        self._set_up_logger()
        self._driver = uc.Chrome()
        self._driver.implicitly_wait(3)  # Tell driver to wait 5 seconds before returning NoSuchElementException
        
        self._open_dnb_first_time()

    """
    Open Duns Bradstreet search page. Close cookie pop-up if shows up
    """
    def _open_dnb_first_time(self) -> None:
        self._driver.get(self._duns_bradstreet_url)
        time.sleep(2) 
        # Close cookie pop-up
        try:
            cookie_close_button = self._driver.find_element(By.ID, "truste-consent-required")
            cookie_close_button.click()
        except NoSuchElementException:
            pass
        time.sleep(2)

    def _set_up_logger(self) -> None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        logging.StreamHandler().setLevel(logging.INFO)
        self._logger = logging.getLogger()
        self._logger.setLevel(logging.INFO)

    def execute_search(self, company_name, company_state, company_city="", company_zip="") -> list[dict]:

        self._reset_search_page()
        self._search_for_company(company_name, company_city, company_zip, company_state)

        if self._check_for_error():
            self._logger.error("DNB system error!!!! Rotate IP address?")
            raise RuntimeError("DNB system error")

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
        self._logger.info(f"found {num_results_divs} results divs")
        for result_index in range(num_results_divs):
            all_duns_results.append(self._email_and_extract_duns_result(result_index))

        return all_duns_results

    # Process an individual search result
    def _email_and_extract_duns_result(self, result_index: int) -> None:
        self._logger.info(f"Processing dnb result #{result_index}")

        result_div = self._find_and_scroll_to_result_div(result_index)
        duns_results = self._extract_company_info(result_div)
        self._request_email_for_result(result_div)

        success_modal = self._look_for_success_modal()
        if success_modal is not None:
            self._logger.info(f"Succesfully triggered email for result #{result_index}")
            duns_results["email_success"] = True
        else:
            self._logger.warn(f"Could not trigger email for result #{result_index}")
            duns_results["email_success"] = False

        self._close_modal()
        return duns_results

    """
    Find nth results div and scroll it into view
    Return: results div
    """
    def _find_and_scroll_to_result_div(self, result_index: int) -> WebElement:
        all_results_divs = self._driver.find_elements(By.CLASS_NAME, "search-results-card-container")
        nth_results_div = all_results_divs[result_index]  # Find the nth result div
        time.sleep(0.5)
        self._driver.execute_script("arguments[0].scrollIntoView(true);", nth_results_div)  # Scroll results div into view
        return nth_results_div

    def _request_email_for_result(self, result_div: WebElement):
        email_duns_button = result_div.find_element(By.XPATH, ".//a[contains(text(), 'Email D-U-N-S')]")  # Find 'Email D-U-N-S number' element'
        email_duns_button.click()
        time.sleep(1)

        email_request_div = self._driver.find_element(By.CLASS_NAME, "requestform")
        
        # Fill in the email form fields 
        email_request_div.find_element(By.NAME, 'FIRST_NAME').send_keys('Larry Boy') 
        time.sleep(0.5)
        email_request_div.find_element(By.NAME, 'LAST_NAME').send_keys('Barese')
        time.sleep(0.5)
        email_request_div.find_element(By.NAME, 'EMAIL_ADDRESS').send_keys('thomasapyncheon@gmail.com') 
        time.sleep(0.5)

        # Submit email request form
        final_submit_button = email_request_div.find_element(By.CLASS_NAME, "requestform__submit")
        self._driver.execute_script("arguments[0].scrollIntoView(true);", final_submit_button)
        final_submit_button.click()
        time.sleep(5)

        
    """
    Find success modal telling us email was sent. If it isn't present, return None
    """
    def _look_for_success_modal(self) -> WebElement:
        try:
            success_modal = self._driver.find_element(By.CLASS_NAME, "requestform__background--success")
            return success_modal
        except:
            return None


    """
    Used to close email request modal
    Can be used to hide the success notification or exit a failed email request window
    """
    def _close_modal(self) -> None: 
        close_button = self._driver.find_element(By.CLASS_NAME, "requestform__close")
        self._driver.execute_script("arguments[0].scrollIntoView(true);", close_button)
        close_button.click()
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


    """
    If I've made too many searches from an IP address, D&B will print a message on some searches that reades
    "An unexpected system error has been encountered. If the issue persists please contact support@dnb.com"
    
    Return true if that mesage appears
    """
    def _check_for_error(self) -> bool:
        try:
            error_elem = self._driver.find_element(By.CLASS_NAME, "direct-plus-search-error-text-row")
        except NoSuchElementException:
            return False
        return True
