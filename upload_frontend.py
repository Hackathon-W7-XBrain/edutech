import boto3
import os
import mimetypes
from pathlib import Path

def upload_directory_to_s3(bucket_name, source_dir):
    s3 = boto3.client('s3', region_name='ap-southeast-1')
    source_path = Path(source_dir).resolve()
    
    # MIME types mapping for common web files
    mimetypes.add_type('application/javascript', '.js')
    mimetypes.add_type('text/css', '.css')
    mimetypes.add_type('text/html', '.html')
    
    for root, dirs, files in os.walk(source_path):
        for filename in files:
            local_path = os.path.join(root, filename)
            relative_path = os.path.relpath(local_path, source_path)
            s3_key = relative_path.replace("\\", "/") # Convert Windows paths to S3 keys
            
            content_type, _ = mimetypes.guess_type(local_path)
            if not content_type:
                content_type = 'application/octet-stream'
                
            print(f"Uploading {s3_key} to {bucket_name} as {content_type}...")
            s3.upload_file(
                local_path, 
                bucket_name, 
                s3_key,
                ExtraArgs={'ContentType': content_type}
            )
            
if __name__ == "__main__":
    bucket = os.getenv("STUDYBOT_FRONTEND_BUCKET", "").strip()
    if not bucket:
        raise SystemExit("Missing env var STUDYBOT_FRONTEND_BUCKET (target S3 bucket name).")
    frontend_dir = "frontend"
    print(f"Starting upload to {bucket}...")
    upload_directory_to_s3(bucket, frontend_dir)
    print("Upload complete!")
