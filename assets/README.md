<p align="center">
  <img src="assets/icon_128.png" alt="Parquetto icon" width="96" />
</p>

# Parquetto

A tiny, standalone desktop app for browsing `.parquet` files. No Jupyter,
no browser, no server — just a native window.

The UI is built entirely in Python with Tkinter (included in the Python
standard library). Loading files uses `pandas` + `pyarrow`; the SQL box
runs on Python's built-in `sqlite3` combined with `pandas.DataFrame.to_sql`
/ `pandas.read_sql_query`, so no extra query engine is required.

## Features

- Open any `.parquet` file and browse it in a scrollable table
- **SQL box**: filter and aggregate with real SQL (`SELECT ... FROM data ...`)
- Click a column header to sort ascending/descending
- Quick text search across all columns at once
- Adjustable rows-per-page for smooth scrolling on large files
- Schema / metadata viewer (column names, dtypes, row groups)
- Export the current view to CSV

## Download the exe (no Python required)

Every push to `main` and every tagged release builds `Parquetto.exe`
automatically via GitHub Actions (see `.github/workflows/build.yml`).

- **Tagged release** (e.g. `v1.0.0`): grab `Parquetto.exe` from the
  [Releases](../../releases) page.
- **Latest build off `main`**: go to the **Actions** tab, open the newest
  successful "Build Windows EXE" run, and download the
  `Parquetto-windows` artifact.

Just double-click the exe — no install, no Python needed.

## Running from source

Requires Python 3.9+.

```bash
git clone https://github.com/<your-username>/parquetto.git
cd parquetto
pip install -r requirements.txt
python main.py
```

Or open a file directly from the command line:

```bash
python main.py path/to/data.parquet
```

Then use **File > Open** (or `Ctrl+O`) to load a Parquet file at any time.

On some Linux distributions, Tkinter isn't installed by default alongside
Python. If you see a `ModuleNotFoundError: No module named 'tkinter'`,
install it with your package manager, e.g.:

```bash
sudo apt install python3-tk      # Debian / Ubuntu
sudo dnf install python3-tkinter # Fedora
```

## Using the SQL box

The loaded file is exposed as a table named **`data`**. Type any SQLite-
flavored SQL and press **Run Query** (or `Ctrl+Enter`):

```sql
SELECT * FROM data WHERE amount > 100 ORDER BY amount DESC

SELECT category, COUNT(*) AS n, AVG(amount) AS avg_amount
FROM data
GROUP BY category
ORDER BY avg_amount DESC
```

Queries always run against the originally loaded file, so you can re-run
a fresh query at any time without needing to reload. Click **Reset to
full data** to go back to the unfiltered table. Note: SQLite has no
native array/struct type, so list- or struct-typed parquet columns are
stringified for querying (their values are still visible, just as text).

## Building the exe yourself

PyInstaller can't cross-compile, so building a real `.exe` has to happen
on Windows — either let GitHub Actions do it (above), or build locally:

```bat
build_exe.bat
```

This installs `pyinstaller` and produces `dist\Parquetto.exe`.

## Repo structure

```
parquetto/
├── main.py                        # the entire application
├── requirements.txt                # pandas + pyarrow
├── build_exe.bat                   # local Windows build script
├── assets/
│   ├── icon.png                    # source icon (1024x1024)
│   ├── icon_128.png                # in-app window icon
│   ├── icon.ico                    # Windows exe icon
│   └── icon.icns                   # macOS app icon (for a future Mac build)
├── .github/workflows/build.yml     # CI: builds & releases the exe
├── README.md
└── LICENSE
```

## License

MIT — see [LICENSE](LICENSE).
