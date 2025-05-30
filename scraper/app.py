import asyncio
import argparse
import sys
from pathlib import Path
from typing import List, Dict

from utils import (
    DocumentationScraper,
    save_extraction_results,
    load_discovered_links,
    save_discovered_links,
    filter_links_by_source,
    get_extraction_statistics
)


async def discover_links_command(args) -> List[Dict]:
    """Discover all documentation links and save them."""
    scraper = DocumentationScraper(
        base_url=args.base_url,
        rate_limit_delay=args.delay,
        max_retries=args.retries
    )
    
    links = await scraper.discover_documentation_links()
    
    if links:
        save_discovered_links(links, args.output)
        print(f"Discovery complete. Found {len(links)} articles.")
        
        # Show breakdown by source
        sources = {}
        for link in links:
            source = link.get('source', 'unknown')
            sources[source] = sources.get(source, 0) + 1
        
        print("Articles by source:")
        for source, count in sources.items():
            print(f"  {source}: {count}")
    else:
        print("No links discovered.")
    
    return links


async def extract_articles_command(args) -> None:
    """Extract content from documentation articles."""
    # Load links from file or discover new ones
    if Path(args.links_file).exists():
        print(f"Loading links from {args.links_file}")
        all_links = load_discovered_links(args.links_file)
    else:
        print(f"Links file {args.links_file} not found. Discovering links first...")
        scraper = DocumentationScraper(
            base_url=args.base_url,
            rate_limit_delay=args.delay,
            max_retries=args.retries
        )
        all_links = await scraper.discover_documentation_links()
        save_discovered_links(all_links, args.links_file)
    
    if not all_links:
        print("No links available for extraction.")
        return
    
    # Filter by sources if specified
    if args.sources:
        all_links = filter_links_by_source(all_links, args.sources)
        print(f"Filtered to {len(all_links)} articles from sources: {', '.join(args.sources)}")
    
    # Limit number of articles if specified
    if args.limit > 0:
        all_links = all_links[:args.limit]
        print(f"Limited to first {len(all_links)} articles")
    
    # Extract URLs for processing
    urls = [link['url'] for link in all_links]
    
    # Initialize scraper and process articles
    scraper = DocumentationScraper(
        base_url=args.base_url,
        rate_limit_delay=args.delay,
        max_retries=args.retries
    )
    
    print(f"Starting extraction of {len(urls)} articles...")
    results = await scraper.process_articles_batch(urls, batch_size=args.batch_size)
    
    # Save results
    json_file, csv_file = save_extraction_results(results, args.output)
    
    # Display statistics
    stats = get_extraction_statistics(results)
    print("\nExtraction Statistics:")
    print(f"  Total articles: {stats['total_articles']}")
    print(f"  Successful: {stats['successful_extractions']}")
    print(f"  Failed: {stats['failed_extractions']}")
    print(f"  Success rate: {stats['success_rate']:.1f}%")
    
    if stats['successful_extractions'] > 0:
        print(f"  Average word count: {stats['average_word_count']:.0f}")
        print(f"  Average sections per article: {stats['average_sections']:.1f}")
        print(f"  Articles with images: {stats['articles_with_images']}")


async def retry_failed_command(args) -> None:
    """Retry extraction for failed articles."""
    # Load previous results
    try:
        import json
        with open(args.previous_results, 'r', encoding='utf-8') as f:
            previous_data = json.load(f)
            previous_results = previous_data['articles']
    except FileNotFoundError:
        print(f"Previous results file {args.previous_results} not found.")
        return
    except Exception as e:
        print(f"Error loading previous results: {e}")
        return
    
    # Find failed URLs
    failed_urls = [r['url'] for r in previous_results if not r.get('success', False)]
    
    if not failed_urls:
        print("No failed articles found in previous results.")
        return
    
    print(f"Found {len(failed_urls)} failed articles to retry")
    
    # Retry extraction
    scraper = DocumentationScraper(
        base_url=args.base_url,
        rate_limit_delay=args.delay,
        max_retries=args.retries
    )
    
    retry_results = await scraper.process_articles_batch(failed_urls, batch_size=args.batch_size)
    
    # Combine with previous successful results
    successful_previous = [r for r in previous_results if r.get('success', False)]
    all_combined = successful_previous + retry_results
    
    # Save combined results
    json_file, csv_file = save_extraction_results(all_combined, args.output)
    
    # Show improvement
    new_successful = sum(1 for r in retry_results if r.get('success', False))
    print(f"Retry completed. {new_successful} additional articles extracted successfully.")


def create_argument_parser():
    """Create and configure argument parser."""
    parser = argparse.ArgumentParser(
        description="Documentation Scraper for MoEngage Help Center",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Discover all documentation links
  python app.py discover

  # Extract first 100 articles
  python app.py extract --limit 100

  # Extract only help articles with custom settings
  python app.py extract --sources help --batch-size 3 --delay 2

  # Retry failed extractions
  python app.py retry --previous-results documentation_complete.json
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Discovery command
    discover_parser = subparsers.add_parser('discover', help='Discover documentation links')
    discover_parser.add_argument('--output', default='discovered_links.json',
                               help='Output file for discovered links (default: discovered_links.json)')
    
    # Extraction command
    extract_parser = subparsers.add_parser('extract', help='Extract article content')
    extract_parser.add_argument('--links-file', default='discovered_links.json',
                               help='JSON file containing discovered links (default: discovered_links.json)')
    extract_parser.add_argument('--limit', type=int, default=0,
                               help='Limit number of articles to extract (0 = no limit)')
    extract_parser.add_argument('--sources', nargs='+', choices=['help', 'developers', 'partners'],
                               help='Filter by source types')
    extract_parser.add_argument('--output', default='documentation',
                               help='Output filename prefix (default: documentation)')
    extract_parser.add_argument('--batch-size', type=int, default=5,
                               help='Number of articles to process simultaneously (default: 5)')
    
    # Retry command
    retry_parser = subparsers.add_parser('retry', help='Retry failed extractions')
    retry_parser.add_argument('--previous-results', required=True,
                            help='JSON file containing previous extraction results')
    retry_parser.add_argument('--output', default='documentation_retry',
                            help='Output filename prefix (default: documentation_retry)')
    retry_parser.add_argument('--batch-size', type=int, default=5,
                            help='Number of articles to process simultaneously (default: 5)')
    
    # Global arguments
    for subparser in [discover_parser, extract_parser, retry_parser]:
        subparser.add_argument('--base-url', default='https://help.moengage.com',
                             help='Base URL for documentation (default: https://help.moengage.com)')
        subparser.add_argument('--delay', type=float, default=1.0,
                             help='Delay between batches in seconds (default: 1.0)')
        subparser.add_argument('--retries', type=int, default=3,
                             help='Maximum number of retries for failed requests (default: 3)')
    
    return parser


async def main():
    """Main application entry point."""
    parser = create_argument_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    try:
        if args.command == 'discover':
            await discover_links_command(args)
        elif args.command == 'extract':
            await extract_articles_command(args)
        elif args.command == 'retry':
            await retry_failed_command(args)
        else:
            print(f"Unknown command: {args.command}")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        import playwright
    except ImportError:
        print("Error: playwright is not installed. Install it with: pip install playwright")
        print("Then run: playwright install")
        sys.exit(1)
    
    asyncio.run(main())