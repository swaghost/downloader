"""Test script to launch GUI with debug logging for video controls"""
import sys
import logging

# Configure logging to show INFO and DEBUG messages
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Set GUI logger to INFO level
gui_logger = logging.getLogger('gui')
gui_logger.setLevel(logging.INFO)

# Now import and run main
import main

if __name__ == '__main__':
    main.main()
