# documentation scraper

extracts articles from moengage help docs using playwright.

## setup

```bash
pip install -r requirements.txt
playwright install
```

## how to use

### find all articles
```bash
python app.py discover
```

### extract articles
```bash
# get all articles
python app.py extract

# get first 100
python app.py extract --limit 100

# get only help articles  
python app.py extract --sources help

# slower extraction (be nice to servers)
python app.py extract --delay 2 --batch-size 3
```

### retry failed ones
```bash
python app.py retry --previous-results documentation_complete.json
```

## outputs

- `documentation_complete.json` - full data with article content
- `documentation_summary.csv` - simple table with urls and stats

## useful options

- `--limit 50` - only extract first 50 articles
- `--sources help developers` - only get articles from these sources
- `--delay 2` - wait 2 seconds between batches
- `--batch-size 3` - process 3 articles at once
- `--output my_docs` - custom filename prefix

## examples

```bash
# basic usage
python app.py discover
python app.py extract --limit 100

# careful extraction 
python app.py extract --delay 3 --batch-size 2 --sources help

# retry failures
python app.py retry --previous-results documentation_complete.json
```

that's it.