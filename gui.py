import asyncio
import threading
import tkinter as tk
from google_scraper_AI import GoogleMapsScraper
from tkinter import messagebox, scrolledtext
from functools import partial 

class ScraperGUI:
    """
    Manages the Tkinter Graphical User Interface and user interactions.
    It handles starting, pausing, and resuming the scraper thread.
    """
    def __init__(self, master: tk.Tk):
        self.master = master
        master.title("Google Maps Scraper")
        master.geometry("650x550")
        master.protocol("WM_DELETE_WINDOW", self._on_closing)

        # State variables
        self.scraper_thread = None
        self.is_paused = False
        self.pause_event = threading.Event()
        self.pause_event.set()  # Set to True initially (not paused)
        self.headless_var = tk.BooleanVar(value=True)
        self._setup_widgets()

    def _setup_widgets(self):
        """Creates and arranges all the GUI elements."""
        main_frame = tk.Frame(self.master, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Input fields
        tk.Label(main_frame, text="Categories (comma-separated):").grid(row=0, column=0, sticky="w", pady=2)
        self.categories_entry = tk.Entry(main_frame)
        self.categories_entry.grid(row=0, column=1, sticky="ew", pady=2)
        self.categories_entry.insert(0, "hastane, eczane")

        tk.Label(main_frame, text="Locations (comma-separated):").grid(row=1, column=0, sticky="w", pady=2)
        self.locations_entry = tk.Entry(main_frame)
        self.locations_entry.grid(row=1, column=1, sticky="ew", pady=2)
        self.locations_entry.insert(0, "İzmit, Kartepe")

        tk.Label(main_frame, text="Max Results per Search:").grid(row=2, column=0, sticky="w", pady=2)
        self.total_entry = tk.Entry(main_frame)
        self.total_entry.grid(row=2, column=1, sticky="ew", pady=2)
        #self.total_entry.insert(0, "100")



        # Buttons
        button_frame = tk.Frame(main_frame)
        button_frame.grid(row=3, column=0, columnspan=3, pady=10)

        self.input_file_button = tk.Button(button_frame, text="Read Input File", command=partial(self.start_scraping, True))
        self.input_file_button.pack(side=tk.LEFT, padx=5)

        self.start_button = tk.Button(button_frame, text="Start Scraping", command=partial(self.start_scraping, False))
        self.start_button.pack(side=tk.LEFT, padx=5)
        
        self.pause_button = tk.Button(button_frame, text="Pause", command=self.toggle_pause, state=tk.DISABLED)
        self.pause_button.pack(side=tk.LEFT, padx=5)

        self.headless_check = tk.Checkbutton(main_frame, text="Run in Headless Mode (faster, no visible browser)", variable=self.headless_var)
        self.headless_check.grid(row=4, column=0, columnspan=3, sticky="w", pady=5)

        # Status area
        tk.Label(main_frame, text="Log:").grid(row=5, column=0, sticky="w", pady=2)
        self.status_text = scrolledtext.ScrolledText(main_frame, wrap=tk.WORD, height=15, state=tk.DISABLED)
        self.status_text.grid(row=6, column=0, columnspan=2, sticky="nsew")

        main_frame.grid_columnconfigure(1, weight=1)
        main_frame.grid_rowconfigure(6, weight=1)

    def update_status(self, message: str):
        """
        Thread-safe method to update the status text area from any thread.
        """
        def _update():
            self.status_text.config(state=tk.NORMAL)
            self.status_text.insert(tk.END, f"{message}\n")
            self.status_text.see(tk.END)  # Auto-scroll to the bottom
            self.status_text.config(state=tk.DISABLED)
        
        if self.master.winfo_exists():
            self.master.after(0, _update)

    def start_scraping(self, readfile: bool):
        """Validates inputs and starts the scraping process in a new thread."""
        search_queries = []
        total_str = self.total_entry.get().strip()
        
        if readfile:
            try:
                with open("input.txt", "r", encoding="utf-8-sig") as file:
                    search_queries = [line.rstrip() for line in file]
            except Exception as e:
                print(f"Error in reading the file: {e}")

        else:
            categories_str = self.categories_entry.get().strip()
            locations_str = self.locations_entry.get().strip()
            
            if not categories_str or not locations_str:
                messagebox.showerror("Input Error", "Please provide at least one category and location.")
                return 
            else:
                search_queries = [f"{c.strip()} {l.strip()}" for c in categories_str.strip(",") for l in locations_str.strip(",")]

        try:
            total_results = int(total_str) if total_str else 1_000_000
            if total_results <= 0: raise ValueError
        except ValueError:
            messagebox.showerror("Input Error", "Max results must be a positive number.")
            return
        
        self.update_status("--- Starting new scraping session ---")
        self._set_gui_state_running(True)

        # Reset pause state for the new session
        self.is_paused = False
        self.pause_event.set()
        self.pause_button.config(text="Pause")

        # Run the scraper in a daemon thread
        self.scraper_thread = threading.Thread(
            target=self._run_scraper_in_thread,
            args=(
                search_queries,
                total_results
            ),
            daemon=True
        )
        self.scraper_thread.start()

    def _run_scraper_in_thread(self, queries, total_results):
        """
        Sets up a new asyncio event loop for the scraper thread and runs it.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        scraper = GoogleMapsScraper(self.update_status, self.pause_event)
        
        try:
            headless_mode = self.headless_var.get()
            loop.run_until_complete(scraper.run(queries, total_results, headless_mode))
        finally:
            loop.close()
            # Schedule GUI update on the main thread
            self.master.after(0, self._set_gui_state_running, False)

    def toggle_pause(self):
        """Toggles the paused state of the scraper."""
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.pause_event.clear()  # Blocks the thread where wait() is called
            self.pause_button.config(text="Resume")
            self.update_status(">>> Scraping paused. <<<")
        else:
            self.pause_event.set()  # Unblocks the thread
            self.pause_button.config(text="Pause")
            self.update_status(">>> Scraping resumed. <<<")

    def _set_gui_state_running(self, is_running: bool):
        """Enables or disables GUI elements based on the scraper's state."""
        if is_running:
            self.start_button.config(state=tk.DISABLED)
            self.pause_button.config(state=tk.NORMAL)
        else:
            self.start_button.config(state=tk.NORMAL)
            self.pause_button.config(state=tk.DISABLED)

    def _on_closing(self):
        """Handles the window close event to ensure clean shutdown."""
        if self.scraper_thread and self.scraper_thread.is_alive():
            if messagebox.askyesno("Exit", "Scraper is still running. Are you sure you want to exit?"):
                # A more graceful shutdown would involve signaling the thread to stop.
                # For now, we just destroy the window, and the daemon thread will exit.
                self.master.destroy()
            else:
                return # Do not close
        self.master.destroy()