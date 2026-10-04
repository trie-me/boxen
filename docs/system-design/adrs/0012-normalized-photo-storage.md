# ADR-0012: Normalize new photo uploads

- **Status:** Accepted
- **Date:** 2026-10-04

## Decision

Store new JPEG, PNG and WebP uploads as WebP at quality 85, with a maximum longest edge of 2,048 pixels and no upscaling. Apply EXIF orientation, retain transparency and strip embedded metadata. Keep the existing restricted subprocess, input byte/pixel limits and single-frame validation. Thumbnails are limited to 480 pixels.

The normalized WebP becomes the immutable, content-addressed original. Hashes, byte sizes, dimensions and content types describe those stored bytes. Display and original storage keys point to the same file for new uploads. Raw incoming bytes remain in staging only and are removed on success, duplicate uploads and failures.

## Compatibility and consequences

This supersedes the baseline's retention of raw incoming originals for new uploads. Existing originals are not migrated or recompressed. The original content endpoint continues to return each record's actual stored format. Backups include normalized and legacy originals; offline derivative repair only rebuilds previews from staging copies. No database migration or new configuration is needed.

Storage and subsequent backups avoid oversized source files and a duplicate full-size preview. Upload normalization is lossy and discards higher resolution and metadata; users needing source files must retain their own copies. Existing data and previous backups will not shrink automatically.
