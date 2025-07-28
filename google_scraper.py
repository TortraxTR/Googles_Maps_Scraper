from playwright.async_api import async_playwright
import asyncio
import re
import os
import random
from business import Business, BusinessList
from ui_selectors import UI_SELECTORS

def extract_coordinates_from_url(url):
    """
    A helper function to parse latitude and longitude from a Google Maps URL.
    Example URL: https://www.google.com/maps/place/business/@34.05,-118.24,15z
    """
    try:
        coords_part = url.split('/@')[-1].split('/')[0]
        lat_str, lon_str = coords_part.split(',')[:2]
        return float(lat_str), float(lon_str)
    except (IndexError, ValueError):
        # Return None if the URL format is unexpected and coordinates can't be found
        return None, None

class GoogleMapsScraper:
    """
    This class encapsulates the core scraping logic. It is designed to be run
    within a separate thread to not block the GUI.
    """
    def __init__(self, gui_update_callback, pause_event):
        self.update_status = gui_update_callback
        self.pause_event = pause_event
        self.business_list = BusinessList()
        # A lock is crucial to prevent race conditions when tasks run in parallel
        self.lock = asyncio.Lock()

    async def run(self, search_queries, total_results, headless_mode):
        """
        The main entry point for the scraper. It launches a browser and then runs
        all search queries in parallel tasks.
        """
        if not search_queries:
            self.update_status("No valid search queries. Please check your inputs.")
            return

        try:
            async with async_playwright() as p:
                # Launch browser once for all concurrent tasks
                browser = await p.chromium.launch(headless=headless_mode)
                context = await browser.new_context()
                self.update_status("Browser instance started.")
                
                semaphore = asyncio.Semaphore(os.cpu_count()-2)
                # Create a list of concurrent tasks, one for each query
                
                query_tasks = [
                    self._process_query(browser, query, total_results, semaphore)
                    for query in search_queries
                ]

                await asyncio.gather(*query_tasks)
                
                self.update_status(f"Starting e-mail extraction...")
                email_tasks = [self._extract_email_from_website(business, context, semaphore) for business in self.business_list.business_list]

                await asyncio.gather(*email_tasks)
                await browser.close()
                self.update_status("Browser instance closed.")

                # Save the accumulated data after all parallel tasks are finished
                if self.business_list.business_list:
                    filename_base = search_queries[0].replace(' ', '_')
                    if len(search_queries) > 1:
                        filename_base += f"_and_{len(search_queries) - 1}_others"
                    
                    saved_file = self.business_list.save_data(filename_base)
                    if saved_file:
                        self.update_status(f"All collected data saved to '{saved_file}'.")
                        
                else:
                    self.update_status("Scraping session finished, but no data was collected.")

                self.business_list = BusinessList()  # Reset for a potential next run
                self.update_status("Scraping session finished successfully!")

        except Exception as e:
            self.update_status(f"A critical error occurred: {e}")
            print(f"Error: {e}")

    async def _process_query(self, browser, query, total_results, semaphore):
        """
        Handles the entire scraping process for a single query in its own page (tab).
        This method is designed to be run as a concurrent task.
        """
        async with semaphore:
            self.pause_event.wait()
            context = await browser.new_context()
            page = await context.new_page()
            try:
                await page.goto("https://www.google.com/maps", timeout=60000)
                await self._perform_search(page, query)
                await self._scrape_results(page, query, total_results)
            except Exception as e:
                self.update_status(f"ERROR: Could not process query '{query}': {e}")
                print(f"Error processing query '{query}': {e}")
            finally:
                await page.close()
                self.update_status(f"Data extraction for query '{query}' is completed.")

    async def _add_business_safely(self, business):
        """
        A thread-safe method to add a business to the shared list. It uses a lock
        to ensure that only one task can modify the list at a time.
        """
        async with self.lock:
            self.business_list.add_business(business)

    async def _perform_search(self, page, query):
        """Handles the process of typing a search query and executing it."""
        self.pause_event.wait() # Check if pause event is set
        search_box = page.locator(UI_SELECTORS["search_input"])
        await search_box.fill(query)
        await asyncio.sleep(random.randrange(2,3)) #Random pause to simulate user behaviour
        
        await page.keyboard.press("Enter")
        self.update_status(f"Searching for '{query}'...")
        await page.wait_for_url("**/search/**", timeout=30000) # Wait for search results to load
        accept_button = page.get_by_role("button", name="Accept all", exact=False)
        if await accept_button.is_visible():
            await accept_button.click()
            await asyncio.sleep(2)
        
        await asyncio.sleep(3) # Wait for page content to load

    async def _scrape_results(self, page, query, total_results):
        """Manages the scraping of search results, including scrolling and data extraction."""
        
        listings = await self._scroll_and_collect_listings(page, query, total_results)

        if not listings:
            self.update_status(f"No list found for '{query}'. Checking for a single result page.")
            business = await self._extract_business_data(page, query)
            if business and business.name:
                await self._add_business_safely(business)
                self.update_status(f"Scraped single business for '{query}': {business.name}")
        else:
            self.update_status(f"Found {len(listings)} listings for '{query}'. Extracting data...")
            for i, listing_locator in enumerate(listings):
                self.pause_event.wait() # Check for pause before each item
                try:
                    await listing_locator.click()
                    await page.wait_for_load_state('domcontentloaded', timeout=15000)
                    await asyncio.sleep(random.randrange(2,4)) # Wait for details to render
                    
                    business = await self._extract_business_data(page, query)
                    if business and business.name:
                        await self._add_business_safely(business)
                        if ((i+1) % 5) == 0:
                            self.update_status(f"  ({i+1}/{len(listings)}) Scraped for '{query}'.")
                            
                except Exception as e:
                    self.update_status(f"  Error scraping listing {i+1} for '{query}': {e}")
                    continue

    async def _scroll_and_collect_listings(self, page, query, total_results):
        """Scrolls down the search results pane to load all businesses."""
        listings_locator = page.locator(UI_SELECTORS["search_results_list"])
        
        # Wait for the initial list to be visible
        try:
            await listings_locator.first.wait_for(timeout=10000)
        except Exception:
            self.update_status(f"Could not find initial business listings for '{query}'.")
            return []

        previously_counted = 0
        while True:
            self.pause_event.wait() # Check if pause event is set
            current_count = await listings_locator.count()

            if current_count >= total_results:
                #self.update_status(f"Reached target of {total_results} listings for '{query}'.")
                break
            
            if current_count == previously_counted and current_count > 0:
                #self.update_status(f"Scrolled to the end for '{query}'. Found {current_count} listings.")
                break

            previously_counted = current_count
            
            # Scroll the pane, not the whole page
            await listings_locator.last.hover()
            await page.mouse.wheel(0, random.randint(8000, 10000))
            await asyncio.sleep(random.randrange(2,4)) # Wait for new results to load

        # Return only up to total_results listings
        return (await listings_locator.all())[:total_results]

    async def _extract_email_from_website(self, business, context, semaphore):
        """
        Navigates to the given website URL and attempts to extract an email address.
        It tries to find common email patterns in the page content.
        """
        
        async with semaphore:
            website_url = business.website.strip()
            if not website_url:
                return None # Skip if website URL is invalid
            
            # Email regex, inefficient but works
            email_regex = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
            email_list = []

            try:
                # Create a new page context to navigate to the website
                website_page = await context.new_page()
            
                # Try to navigate to the website
                await website_page.goto(website_url, timeout=0, wait_until="domcontentloaded")
                
                accept_button = website_page.get_by_role("button", name="Accept all", exact=False)
                if await accept_button.is_visible():
                    await accept_button.click()
                    await asyncio.sleep(random.randrange(2,4))
                await asyncio.sleep(random.randrange(2,4)) # Give some time for content to load
                
                # Get text content of the entire page
                page_content = await website_page.content()

                # Search for email in the main content
                email_list = re.findall(email_regex, page_content)
                if email_list:
                    business.email_list = email_list
                    #self.update_status(f"Found emails on main site: {email_list}")
                
                # If no email found on main page, try common contact pages
                else:
                    contact_page_urls = [f"{website_url}/iletisim", f"{website_url}/tr/iletisim", f"{website_url}/contact", f"{website_url}/tr/contact"]
                    for contact_url in contact_page_urls:
                        try:
                            await website_page.goto(contact_url, timeout=0, wait_until="domcontentloaded")
                            await asyncio.sleep(random.randrange(1,2))
                            contact_page_content = await website_page.content()
                            business.email_list = business.email_list.append(re.findall(email_regex, contact_page_content))
                        except Exception:
                            # Ignore errors for non-existent contact pages
                            continue

            except Exception as e:
                if ("ERR_NAME_NOT_RESOLVED" in e.message):
                    self.update_status(f"  Error accessing website for {website_url}: Link is not accessible.")
                elif ("ERR_CONNECTION_RESET" in e.message):
                    self.update_status(f"  Error accessing website for {website_url}: Connection reset.")
                elif ("ERR_TIMED_OUT" in e.message):
                    self.update_status(f"  Error accessing website for {website_url}: Connection timed out.")
                else:
                    self.update_status(f"  Uncaught error while extracting email from {website_url}: {e}")
            
            finally:
                await website_page.close()


    async def _extract_business_data(self, page, query):
        """Extracts the details of a single business from the page."""
        
        async def get_text(selector):
            """Helper to safely get text from a locator."""
            try:
                return await page.locator(selector).first.inner_text(timeout=2000)
            except Exception:
                return ""

        name = await get_text(UI_SELECTORS["business_name"])
        address = await get_text(UI_SELECTORS["address"])
        website = await get_text(UI_SELECTORS["website"])
        phone = await get_text(UI_SELECTORS["phone_number"])
        lat, lon = extract_coordinates_from_url(page.url)

        return Business(
            name=name.strip(),
            address=address.strip(),
            website=f"https://www.{website.strip()}" if website and not website.strip().startswith("http") else website.strip(),
            phone_number=phone.strip(),
            query=query,
            latitude=lat,
            longitude=lon,
            email_list=None # Pass the extracted email
        )
    