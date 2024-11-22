import csv
import logging
import time
import re
from datetime import timedelta

import arrow
import undetected_chromedriver as uc
from selenium.common.exceptions import ElementClickInterceptedException, NoSuchElementException, StaleElementReferenceException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait


# Aka they've caught us scraping
class DNBServerException(RuntimeError):
    pass

# immediately switch vpn servers...
class DNBRejectionException(RuntimeError):
    pass

class DBScraper:
    def __init__(self, logger=None):
        self._duns_bradstreet_url = "https://www.dnb.com/duns-number/lookup.html"
        self._logger = logger
        self._driver = None
        self._initialize()

    def _initialize(self):
        self._set_up_logger()
        self._driver = uc.Chrome()
        self._driver.implicitly_wait(3)  # Tell driver to wait 5 seconds before returning NoSuchElementException
        
        self._load_dnb_search_page()

    """
    Open Duns Bradstreet search page. Close cookie pop-up if shows up
    params:
        handle_cookie_popup (bool): If true, look for and close the GDPR cookie popup 
    """
    def _load_dnb_search_page(self, handle_cookie_popup: bool = True) -> None:
        self._driver.get(self._duns_bradstreet_url)
        time.sleep(2) 
        # Close cookie pop-up
        self._handle_cookie_popup()

    """
    Closes the GDPR cookie pop-up if it's present
    """
    def _handle_cookie_popup(self) -> None:
        try:
            cookie_close_button = self._driver.find_element(By.ID, "truste-consent-required")
            cookie_close_button.click()
        except NoSuchElementException:
            pass
        time.sleep(2)
        

    def _set_up_logger(self) -> None:
        if self._logger is not None: return
        logging.basicConfig(level=logging.INFO, 
                            format="%(asctime)s %(levelname)s: %(message)s", 
                            datefmt="%Y-%m-%d %H:%M:%S")
        logging.StreamHandler().setLevel(logging.INFO)
        self._logger = logging.getLogger()
        self._logger.setLevel(logging.INFO)

    """
    Check whether DNB is showing us an "access denied" screen
    """
    def _check_access_denied(self) -> True:
        try:
            first_h1 = self._driver.find_element(By.TAG_NAME, "h1")
            if "Access Denied" in first_h1.text:
                return True
        except NoSuchElementException:
            pass
        return False

    """
    Entrypoint to DNB screaper. Searches for a company by name/city/state, then extracts information from search results and generates a DNB number email
    params:
        company_name(str)
        company_state(str)
        company_cit(str)
        company_zip(str)
        new_vpn_server(bool): True if we've just switched VPN servers. After switching servers, we need to check for the cookie popup again
    """
    def execute_search(self, company_name: str, company_state: str, company_city="", company_zip="", new_vpn_server=False) -> list[dict]:


        max_search_tries=3
        try_number = 1
        # This is ugly. I should just wrap a retry decorator around the reset_search_page and _search_for_company methods...
        while try_number <= max_search_tries:
            try:
                self._load_dnb_search_page(handle_cookie_popup=False)
                if self._check_access_denied():
                    raise DNBServerException("DNB Access Denied. Rotate VPN")
                self._search_for_company(company_name, company_city, company_zip, company_state)
                break
            except NoSuchElementException:
                self._logger.error(f"Could not find search container on attempt {try_number}/{max_search_tries}")
            except WebDriverException:
                self._logger.error(f"Could not load search page on attemp {try_number}/{max_search_tries}")

            try_number += 1

        if try_number >= max_search_tries:
            self._logger.error("Could not locate search container after {max_search_tries} tries. Rotate server?")
            raise DNBServerException()


        if self._check_for_error():
            self._logger.error("DNB server error!!!! Rotate IP address?")
            raise DNBServerException("DNB server error")

        duns_results = self._email_and_extract_duns_results()
        duns_results = [duns_result | {"company_name_search_term": company_name} for duns_result in duns_results]
        return duns_results

    def _search_for_company(self, company_name: str, company_city: str, company_zip: str, company_state: str) -> None:
        search_type_selector = Select(self._driver.find_element(By.NAME, "primary-reason-dropdown-select-component"))
        search_type_selector.select_by_visible_text("Other company")
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
        self._center_element(search_box)
        time.sleep(0.2)

        search_box.submit() 
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
        self._logger.info(f"Processing dnb result #{result_index+1}")

        result_div = self._find_and_scroll_to_result_div(result_index)
        duns_results = self._extract_company_info(result_div)
        self._request_email_for_result(result_div)

        success_modal = self._look_for_success_modal()
        if success_modal is not None:
            self._logger.info(f"Succesfully triggered email for result #{result_index+1}")
            duns_results["email_success"] = True
            duns_results["time_email_requested"] = arrow.now() - timedelta(seconds=5)
        else:
            self._logger.warn(f"Could not trigger email for result #{result_index+1}")
            time.sleep(1)  
            duns_results["email_success"] = False

        # :). Sorry. Use retry decorator later
        try:
            self._close_modal()
        except (StaleElementReferenceException, ElementClickInterceptedException):
            breakpoint()
        return duns_results

    """
    Find nth results div and scroll it into view
    Return: results div
    """
    def _find_and_scroll_to_result_div(self, result_index: int) -> WebElement:
        all_results_divs = self._driver.find_elements(By.CLASS_NAME, "search-results-card-container")
        nth_results_div = all_results_divs[result_index]  # Find the nth result div
        time.sleep(0.5)
        self._center_element(nth_results_div)  # Scroll results div into view
        return nth_results_div

    def _request_email_for_result(self, result_div: WebElement):
        email_duns_button = result_div.find_element(By.XPATH, ".//a[contains(text(), 'Email D-U-N-S')]")  # Find 'Email D-U-N-S number' element'
        email_duns_button.click()
        time.sleep(1)

        email_request_div = self._driver.find_element(By.CLASS_NAME, "requestform")
        
        # Fill in the email form fields 
        email_request_div.find_element(By.NAME, 'FIRST_NAME').send_keys('Ally Boy') 
        time.sleep(0.5)
        email_request_div.find_element(By.NAME, 'LAST_NAME').send_keys('Barese')
        time.sleep(0.5)
        email_request_div.find_element(By.NAME, 'EMAIL_ADDRESS').send_keys('thomasapyncheon@gmail.com') 
        time.sleep(0.5)

        # Submit email request form
        final_submit_button = email_request_div.find_element(By.CLASS_NAME, "requestform__submit")
        self._center_element(final_submit_button)
        time.sleep(1)
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
        # gonna try sleeping for a second before entering this method to see if that resolves below...
        # Traceback (most recent call last):
        #   File "/Users/ajr74/hub/duns-bradstreet-scraper/toy.py", line 160, in <module>
        #     duns_results = scraper.execute_search(
        #                    ^^^^^^^^^^^^^^^^^^^^^^^
        #   File "/Users/ajr74/hub/duns-bradstreet-scraper/duns_bradstreet_scraper/duns_bradstreet_scraper.py", line 95, in execute_search
        #     duns_results = self._email_and_extract_duns_results()
        #                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        #   File "/Users/ajr74/hub/duns-bradstreet-scraper/duns_bradstreet_scraper/duns_bradstreet_scraper.py", line 140, in _email_and_extract_duns_results
        #     all_duns_results.append(self._email_and_extract_duns_result(result_index))
        #                             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        #   File "/Users/ajr74/hub/duns-bradstreet-scraper/duns_bradstreet_scraper/duns_bradstreet_scraper.py", line 160, in _email_and_extract_duns_result
        #     self._close_modal()
        #   File "/Users/ajr74/hub/duns-bradstreet-scraper/duns_bradstreet_scraper/duns_bradstreet_scraper.py", line 216, in _close_modal
        #     close_button.click()
        #   File "/opt/homebrew/Caskroom/miniconda/base/envs/py311/lib/python3.11/site-packages/selenium/webdriver/remote/webelement.py", line 94, in click
        #     self._execute(Command.CLICK_ELEMENT)
        #   File "/opt/homebrew/Caskroom/miniconda/base/envs/py311/lib/python3.11/site-packages/selenium/webdriver/remote/webelement.py", line 395, in _execute
        #     return self._parent.execute(command, params)
        #            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        #   File "/opt/homebrew/Caskroom/miniconda/base/envs/py311/lib/python3.11/site-packages/selenium/webdriver/remote/webdriver.py", line 354, in execute
        #     self.error_handler.check_response(response)
        #   File "/opt/homebrew/Caskroom/miniconda/base/envs/py311/lib/python3.11/site-packages/selenium/webdriver/remote/errorhandler.py", line 229, in check_response
        #     raise exception_class(message, screen, stacktrace)
        # selenium.common.exceptions.ElementClickInterceptedException: Message: element click intercepted: Element <button class="requestform__close" aria-label="Request Form close button">...</button> is not clickable at point (12
        # 63, 351). Other element would receive the click: <span class="full-screen-loader"></span>
        #   (Session info: chrome=127.0.6533.120)Message: no such element: Unable to locate element: {"method":"css selector","selector":".full-screen-loader"}
        time.sleep(4) # ???????????????
        close_button = self._driver.find_element(By.CLASS_NAME, "requestform__close")
        self._center_element(close_button)
        close_button.click()
        time.sleep(1.5)

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
    Scroll to vertically center element in viewport
    """
    def _center_element(self, elem: WebElement) -> None:
        desired_y = (elem.size["height"] / 2) + elem.location["y"]
        window_h = self._driver.execute_script("return window.innerHeight")
        window_y = self._driver.execute_script("return window.pageYOffset")
        current_y = (window_h / 2) + window_y
        scroll_y_by = desired_y - current_y
        self._driver.execute_script("window.scrollBy(0, arguments[0]);", scroll_y_by)  # Scroll results div into view


    """
    If I've made too many searches from an IP address, D&B will print a message on some searches that reades
    "An unexpected system error has been encountered. If the issue persists please contact support@dnb.com"
    
    Return true if that mesage appears
    """
    def _check_for_error(self) -> bool:
        try:
            error_elem = self._driver.find_element(By.CLASS_NAME, "direct-plus-search-error-text")
            return True
        except NoSuchElementException:
            return False
