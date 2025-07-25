from dataclasses import asdict, dataclass, field
import datetime
import os
import pandas as pd

@dataclass
class Business:
    """
    A dataclass to hold the information for a single business.
    Using a dataclass provides type hints and a structured way to store data.
    """
    name: str
    address: str
    phone_number: str 
    website: str
    email_list: list[str]
    query: str 
    latitude: float
    longitude: float

    def __hash__(self):
        """
        Makes the Business object hashable for use in sets, which is crucial
        for detecting and removing duplicate entries. A business is considered
        a duplicate if its name and at least one piece of contact information
        (website or phone) are the same.
        """
        # Create a tuple of the core identifying fields for hashing.
        # This helps in identifying unique businesses.
        hash_fields = (
            self.name,
            self.website,
            self.phone_number,
        )
        return hash(hash_fields)

@dataclass
class BusinessList:
    """
    Manages a list of Business objects and handles saving the data to files.
    """
    business_list: list[Business] = field(default_factory=list)
    _seen_businesses: set[int] = field(default_factory=set, init=False)

    def add_business(self, business: Business):
        """
        Adds a new business to the list, but only if it hasn't been seen before.
        This prevents duplicate records in the final output.
        """
        business_hash = hash(business)
        if business_hash not in self._seen_businesses:
            self.business_list.append(business)
            self._seen_businesses.add(business_hash)

    def to_dataframe(self) -> pd.DataFrame:
        """
        Converts the list of Business objects into a pandas DataFrame.
        This is a convenient format for data manipulation and saving.
        """
        # The asdict function converts each dataclass instance to a dictionary.
        return pd.json_normalize(
            (asdict(b) for b in self.business_list), sep="_"
        )

    def save_data(self, filename_base):
        """
        Saves the collected business data to both Excel and CSV files.
        Files are stored in a dated folder for better organization.
        """
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        save_path = os.path.join('Google_Maps_Data', today_str)
        os.makedirs(save_path, exist_ok=True)

        df = self.to_dataframe()
        if not df.empty:
            df.to_excel(f"{save_path}/{filename_base}.xlsx", index=False)
            #df.to_csv(f"{save_path}/{filename_base}.csv", index=False)
            return f"{save_path}/{filename_base}"
        return None