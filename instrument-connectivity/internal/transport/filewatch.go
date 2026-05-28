package transport

import (
    "path/filepath"

    "github.com/fsnotify/fsnotify"
)

type FileWatcher struct { watcher *fsnotify.Watcher }
func NewFileWatcher() (*FileWatcher, error) { w, err := fsnotify.NewWatcher(); if err != nil { return nil, err }; return &FileWatcher{watcher: w}, nil }
func (fw *FileWatcher) Add(path string) error { return fw.watcher.Add(path) }
func (fw *FileWatcher) Events() <-chan fsnotify.Event { return fw.watcher.Events }
func (fw *FileWatcher) Errors() <-chan error { return fw.watcher.Errors }
func (fw *FileWatcher) Close() error { return fw.watcher.Close() }
func NormalizeWatchedPath(path string) string { return filepath.Clean(path) }
