import sys
from node import main

if __name__ == "__main__":
    # Pass command-line arguments to node.py's main()
    sys.argv[0] = "node.py"  # For argparse compatibility
    main()
