import requests

url = "https://www.marchespublics.gov.ma/index.php?page=entreprise.EntrepriseDownloadCompleteDce&reference=910643&orgAcronym=q1s"

# Add headers to simulate a real browser request
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

response = requests.get(url, headers=headers)

# Check if the request was successful
if response.status_code == 200:
    with open("downloaded_file.zip", "wb") as file:
        file.write(response.content)
    print("File downloaded successfully.")
else:
    print(f"Failed to download. Status code: {response.status_code}")
