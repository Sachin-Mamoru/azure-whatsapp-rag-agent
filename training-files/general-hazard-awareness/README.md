# Training Files

This directory contains PDF files for the RAG (Retrieval-Augmented Generation) system.

## Instructions

1. Place your safety and hazard awareness PDF documents in this directory
2. Supported formats: PDF files only
3. The system will automatically process all PDF files on startup
4. Example files you might include:
   - Safety procedures and guidelines
   - Hazard identification manuals
   - Emergency response protocols
   - Industry-specific safety standards

## File Organization

You can organize files in subdirectories if needed:
- workplace-safety/
- chemical-hazards/
- fire-safety/
- etc.

The system will recursively scan all PDF files in this directory and its subdirectories.

## Notes

- Ensure PDF files are text-searchable (not just scanned images)
- Larger files will take longer to process during startup
- The vector index is rebuilt each time the container starts
- For production, consider implementing persistent vector storage
