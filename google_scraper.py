import asyncio
from business import Business, BusinessList
from ui_selectors import UI_SELECTORS
from playwright.async_api import async_playwright, Page, Locator

def extract_coordinates_from_url(url: str) -> tuple[float | None, float | None]:
    """
    A helper function to parse latitude and longitude from a Google Maps URL.
    Example URL: https://www.google.com/maps/place/business/@34.05,-118.24,15z
    """
    try:
        coords_part = url.split('/@')[-1].split('/')[0]
        lat_str, lon_str = coords_part.split(',')[:2]
        return float(lat_str), float(lon_str)
    except (IndexError, ValueError):
        # Return None if the URL format is unexpected and coordinates can't be found.
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

    async def run(self, search_queries: list[str], total_results: int):
        """
        The main entry point for the scraper. It sets up Playwright and
        iterates through the search queries.
        """

        if not search_queries:
            self.update_status("No valid search queries. Please check your inputs.")
            return

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(locale="en-US")
                await page.goto("https://www.google.com/maps", timeout=60000)

                for i, query in enumerate(search_queries):
                    self.pause_event.wait()  # Checks if paused before starting a new search.
                    self.update_status(f"--- ({i + 1}/{len(search_queries)}) Searching for: {query} ---")
                    await self._perform_search(page, query)
                    await self._scrape_results(page, query, total_results)

                await browser.close()
                self.update_status("Scraping finished successfully!")

        except Exception as e:
            self.update_status(f"An unexpected error occurred: {e}")
            print(f"Error: {e}") # Also print to console for debugging

    async def run_field(self, categories: list[str], locations: list[str], total_results: int):
        """
        The main entry point for the scraper. It sets up Playwright and
        iterates through the search queries.
        """
        search_queries = [f"{cat} {loc}" for cat in categories for loc in locations]
        await self.run_input_file(self, search_queries, total_results)

    async def _perform_search(self, page: Page, query: str):
        """Handles the process of typing a search query and executing it."""
        self.pause_event.wait()
        search_box = page.locator(UI_SELECTORS["search_input"])
        await search_box.fill(query)
        await asyncio.sleep(1) # Brief pause for stability
        await page.keyboard.press("Enter")
        self.update_status(f"Searching for '{query}'...")
        await page.wait_for_url("**/search/**", timeout=30000) # Wait for search results to load
        await asyncio.sleep(3)

    async def _scrape_results(self, page: Page, query: str, total_results: int):
        """Manages the scraping of search results, including scrolling and data extraction."""
        self.update_status("Scrolling to collect all business listings...")
        listings = await self._scroll_and_collect_listings(page, total_results)

        if not listings:
            self.update_status("No listings found. Trying to scrape a single result page.")
            # If no list is found, it might be a direct page for one business.
            business = await self._extract_business_data(page, query)
            if business and business.name:
                self.business_list.add_business(business)
                self.update_status(f"Scraped single business: {business.name}")
        else:
            self.update_status(f"Found {len(listings)} listings. Starting data extraction...")
            for i, listing_locator in enumerate(listings):
                self.pause_event.wait() # Check for pause before each item
                try:
                    await listing_locator.click()
                    await page.wait_for_load_state('domcontentloaded', timeout=15000)
                    await asyncio.sleep(2) # Wait for details to render
                    
                    business = await self._extract_business_data(page, query)
                    if business and business.name:
                        self.business_list.add_business(business)
                        self.update_status(f"  ({i+1}/{len(listings)}) Scraped: {business.name}")

                except Exception as e:
                    self.update_status(f"  Error scraping listing {i+1}: {e}")
                    continue # Move to the next listing

        # Save the collected data for the current search query
        filename_base = f"{query.replace(' ', '_')}"
        saved_file = self.business_list.save_data(filename_base)
        if saved_file:
            self.update_status(f"Saved data to '{saved_file}.xlsx.")
        
        # Clear list for the next search query
        self.business_list = BusinessList()

    async def _scroll_and_collect_listings(self, page: Page, total_results: int) -> list[Locator]:
        """Scrolls down the search results pane to load all businesses."""
        listings_locator = page.locator(UI_SELECTORS["search_results_list"])
        
        # Wait for the initial list to be visible
        try:
            await listings_locator.first.wait_for(timeout=10000)
        except Exception:
            self.update_status("Could not find initial business listings.")
            return []

        previously_counted = 0
        while True:
            self.pause_event.wait()
            current_count = await listings_locator.count()

            if current_count >= total_results:
                self.update_status(f"Reached target of {total_results} listings.")
                break
            
            if current_count == previously_counted and current_count > 0:
                self.update_status(f"Scrolled to the end. Found {current_count} listings.")
                break

            previously_counted = current_count
            self.update_status(f"Currently have {previously_counted} listings, scrolling for more...")
            
            # Scroll the pane, not the whole page
            await listings_locator.last.hover()
            await page.mouse.wheel(0, 10000)
            await asyncio.sleep(3) # Wait for new results to load

        return await listings_locator.all()

    async def _extract_business_data(self, page: Page, query:str) -> Business:
        """Extracts the details of a single business from the page."""
        
        async def get_text(selector: str) -> str:
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
            website=f"https://www.{website.strip()}" if website else "",
            phone_number=phone.strip(),
            query=query,
            latitude=lat,
            longitude=lon
        )