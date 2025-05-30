import asyncio
import json
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright
import time
import re


class DocumentationScraper:
    """Main scraper class for extracting documentation articles."""
    
    def __init__(self, base_url: str = 'https://help.moengage.com', rate_limit_delay: float = 1.0, max_retries: int = 3):
        self.base_url = base_url
        self.rate_limit_delay = rate_limit_delay
        self.max_retries = max_retries
        
    async def discover_documentation_links(self) -> List[Dict[str, str]]:
        """
        Discover all documentation links from the main help page.
        
        Returns:
            List of dictionaries containing url, title, and source information
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox"
                ]
            )
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await context.new_page()
            
            try:
                print("Discovering documentation links...")
                await page.goto(f'{self.base_url}/hc/en-us', wait_until='networkidle')
                
                links = await page.evaluate('''
                    () => {
                        return Array.from(document.querySelectorAll('a[href]')).map(link => ({
                            href: link.href,
                            text: link.textContent.trim(),
                            title: link.title || ''
                        }));
                    }
                ''')

                documentation_patterns = [
                    r'https://help\.moengage\.com/hc/en-us/articles/\d+-',
                    r'https://developers\.moengage\.com/hc/en-us/articles/\d+-',
                    r'https://partners\.moengage\.com/hc/en-us/articles/\d+-'
                ]

                filtered_links = []
                seen_urls = set()

                for link in links:
                    href = link['href']
                    if any(re.match(pattern, href) for pattern in documentation_patterns):
                        if href not in seen_urls:
                            filtered_links.append({
                                'url': href,
                                'title': link['text'],
                                'source': (
                                    'help' if 'help.moengage' in href else
                                    'developers' if 'developers' in href else
                                    'partners'
                                )
                            })
                            seen_urls.add(href)

                print(f"Found {len(filtered_links)} unique documentation articles")
                return filtered_links

            except Exception as e:
                print(f"Error during link discovery: {str(e)}")
                return []
            finally:
                await browser.close()

    async def extract_article_content(self, url: str) -> Dict:
        """
        Extract content from a single documentation article.
        
        Args:
            url: URL of the article to extract
            
        Returns:
            Dictionary containing extracted article content and metadata
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            page = await context.new_page()

            try:
                await page.goto(url, wait_until='networkidle', timeout=30000)

                content = await page.evaluate('''
                    () => {
                        const article = {};

                        // Extract title with fallback selectors
                        const titleSelectors = [
                            'h6.article-title',
                            'h1.article-title',
                            '.article-title',
                            'h1',
                            '.page-title'
                        ];
                        for (const selector of titleSelectors) {
                            const el = document.querySelector(selector);
                            if (el) {
                                article.title = el.textContent.trim();
                                break;
                            }
                        }

                        // Extract main body content
                        const bodyEl = document.querySelector('div.article__body') ||
                                       document.querySelector('.article-body') ||
                                       document.querySelector('.content');

                        if (bodyEl) {
                            const sections = [];
                            let currentSection = { heading: 'Introduction', content: '', images: [] };
                            const children = Array.from(bodyEl.children);

                            children.forEach(child => {
                                const tag = child.tagName.toLowerCase();

                                if (['h1', 'h2', 'h3', 'h4', 'h5', 'h6'].includes(tag)) {
                                    if (currentSection.content.trim()) {
                                        sections.push({ ...currentSection });
                                    }
                                    currentSection = {
                                        heading: child.textContent.trim(),
                                        content: '',
                                        images: [],
                                        level: parseInt(tag.charAt(1))
                                    };
                                } else {
                                    const text = child.textContent.trim();
                                    if (text) {
                                        currentSection.content += text + '\\n\\n';
                                    }
                                    const imgs = child.querySelectorAll('img');
                                    imgs.forEach(img => {
                                        if (img.src) {
                                            currentSection.images.push({
                                                src: img.src,
                                                alt: img.alt || '',
                                                title: img.title || ''
                                            });
                                        }
                                    });
                                }
                            });

                            if (currentSection.content.trim()) {
                                sections.push(currentSection);
                            }

                            article.sections = sections;
                            article.fullText = bodyEl.textContent.trim();
                            article.htmlContent = bodyEl.innerHTML;
                        }

                        article.url = window.location.href;
                        article.wordCount = article.fullText ? article.fullText.split(/\\s+/).length : 0;
                        article.lastModified = document.querySelector('time')?.getAttribute('datetime') || '';

                        const breadcrumbs = Array.from(document.querySelectorAll('.breadcrumbs a, nav a'))
                                                .map(a => a.textContent.trim())
                                                .filter(Boolean);
                        article.breadcrumbs = breadcrumbs;

                        return article;
                    }
                ''')

                content['extractedAt'] = datetime.now().isoformat()
                content['success'] = True
                return content

            except Exception as e:
                print(f"Error extracting {url}: {str(e)}")
                return {
                    'url': url,
                    'error': str(e),
                    'success': False,
                    'extractedAt': datetime.now().isoformat()
                }
            finally:
                await browser.close()

    async def process_articles_batch(self, urls: List[str], batch_size: int = 5) -> List[Dict]:
        """
        Process multiple articles in batches to avoid overwhelming the server.
        
        Args:
            urls: List of URLs to process
            batch_size: Number of articles to process simultaneously
            
        Returns:
            List of extraction results
        """
        all_results = []
        total_batches = (len(urls) + batch_size - 1) // batch_size

        print(f"Processing {len(urls)} articles in {total_batches} batches of {batch_size}")

        for i in range(0, len(urls), batch_size):
            batch = urls[i:i + batch_size]
            batch_num = (i // batch_size) + 1

            print(f"Batch {batch_num}/{total_batches} - processing {len(batch)} articles...")

            # Process batch in parallel
            batch_tasks = [self.extract_article_content(url) for url in batch]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

            # Handle results and exceptions
            for j, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    print(f"Failed: {batch[j]} - {str(result)}")
                    all_results.append({
                        'url': batch[j],
                        'error': str(result),
                        'success': False
                    })
                else:
                    if result.get('success', False):
                        title = result.get('title', 'Untitled')[:50]
                        print(f"Success: {title}...")
                    else:
                        print(f"Partial: {batch[j]}")
                    all_results.append(result)

            # Rate limiting
            if i + batch_size < len(urls):
                await asyncio.sleep(self.rate_limit_delay)

        success_count = sum(1 for r in all_results if r.get('success', False))
        print(f"Completed: {success_count}/{len(urls)} articles successfully extracted")

        return all_results


def save_extraction_results(results: List[Dict], output_prefix: str = 'documentation') -> Tuple[str, str]:
    """
    Save extraction results to JSON and CSV files.
    
    Args:
        results: List of extraction results
        output_prefix: Prefix for output filenames
        
    Returns:
        Tuple of (json_filename, csv_filename)
    """
    successful = [r for r in results if r.get('success', False)]
    
    summary = {
        'extraction_summary': {
            'total_articles': len(results),
            'successful_extractions': len(successful),
            'failed_extractions': len(results) - len(successful),
            'average_word_count': (
                sum(r.get('wordCount', 0) for r in successful) / len(successful)
                if successful else 0
            ),
            'extraction_timestamp': datetime.now().isoformat()
        },
        'articles': results
    }

    # Save detailed JSON
    json_filename = f'{output_prefix}_complete.json'
    with open(json_filename, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # Create CSV summary
    csv_data = []
    for article in successful:
        csv_data.append({
            'url': article.get('url', ''),
            'title': article.get('title', ''),
            'word_count': article.get('wordCount', 0),
            'section_count': len(article.get('sections', [])),
            'has_images': any(len(s.get('images', [])) > 0 for s in article.get('sections', [])),
            'breadcrumbs': ' > '.join(article.get('breadcrumbs', [])),
            'extracted_at': article.get('extractedAt', '')
        })

    csv_filename = f'{output_prefix}_summary.csv'
    df = pd.DataFrame(csv_data)
    df.to_csv(csv_filename, index=False)

    print(f"Saved detailed results to {json_filename}")
    print(f"Saved summary to {csv_filename}")
    print(f"Success rate: {len(successful)}/{len(results)} ({(len(successful)/len(results)*100):.1f}%)")

    return json_filename, csv_filename


def load_discovered_links(filename: str = 'discovered_links.json') -> List[Dict]:
    """
    Load previously discovered links from a JSON file.
    
    Args:
        filename: Path to the JSON file containing discovered links
        
    Returns:
        List of link dictionaries
    """
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"No existing links file found at {filename}")
        return []


def save_discovered_links(links: List[Dict], filename: str = 'discovered_links.json') -> None:
    """
    Save discovered links to a JSON file for reuse.
    
    Args:
        links: List of link dictionaries to save
        filename: Output filename
    """
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(links, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(links)} discovered links to {filename}")


def filter_links_by_source(links: List[Dict], sources: List[str] = None) -> List[Dict]:
    """
    Filter links by source type.
    
    Args:
        links: List of link dictionaries
        sources: List of sources to include ('help', 'developers', 'partners')
        
    Returns:
        Filtered list of links
    """
    if sources is None:
        sources = ['help', 'developers', 'partners']
    
    return [link for link in links if link.get('source') in sources]


def get_extraction_statistics(results: List[Dict]) -> Dict:
    """
    Calculate statistics from extraction results.
    
    Args:
        results: List of extraction results
        
    Returns:
        Dictionary containing statistics
    """
    successful = [r for r in results if r.get('success', False)]
    
    if not successful:
        return {'total': len(results), 'successful': 0, 'failed': len(results)}
    
    word_counts = [r.get('wordCount', 0) for r in successful]
    section_counts = [len(r.get('sections', [])) for r in successful]
    
    return {
        'total_articles': len(results),
        'successful_extractions': len(successful),
        'failed_extractions': len(results) - len(successful),
        'success_rate': (len(successful) / len(results)) * 100,
        'average_word_count': sum(word_counts) / len(word_counts),
        'min_word_count': min(word_counts),
        'max_word_count': max(word_counts),
        'average_sections': sum(section_counts) / len(section_counts),
        'articles_with_images': sum(1 for r in successful 
                                  if any(len(s.get('images', [])) > 0 for s in r.get('sections', [])))
    }