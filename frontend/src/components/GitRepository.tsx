import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8001';

export interface GitCommit {
  hash: string;
  message: string;
  author: string;
  date: string;
}

export interface GitUIState {
  isInitialized: boolean;
  isConnected: boolean;
  repoPath: string;
  loading: boolean;
  error: string | null;
  status: any;
  commits: GitCommit[];
  selectedCommit: GitCommit | null;
  commitDetails: string;
  stageFiles: string[];
  unstageFiles: string[];
  commitMessage: string;
  showCommitConfirmation: boolean;
  showDiff: boolean;
  diffContent: string;
}

export interface GitCallbacks {
  onSuccess?: (msg: string) => void;
  onError?: (msg: string) => void;
}

const initialGitState: GitUIState = {
  isInitialized: false,
  isConnected: false,
  repoPath: '',
  loading: false,
  error: null,
  status: null,
  commits: [],
  selectedCommit: null,
  commitDetails: '',
  stageFiles: [],
  unstageFiles: [],
  commitMessage: '',
  showCommitConfirmation: false,
  showDiff: false,
  diffContent: '',
};

export function useGitRepository(projectId: string | null, callbacks?: GitCallbacks) {
  const [state, setState] = useState<GitUIState>(initialGitState);

  const fetchStatus = useCallback(async () => {
    if (!projectId) return;
    try {
      const res = await axios.get(`${API_URL}/git/status/${projectId}`);
      const isRepo = Boolean(res.data?.is_repo);
      setState(prev => ({
        ...prev,
        status: res.data,
        isInitialized: isRepo,
      }));
    } catch {
      setState(prev => ({
        ...prev,
        status: null,
        isInitialized: false,
      }));
    }
  }, [projectId]);

  const fetchHistory = useCallback(async () => {
    if (!projectId) return;
    try {
      const res = await axios.get(`${API_URL}/git/history/${projectId}`);
      setState(prev => ({
        ...prev,
        commits: (res.data?.commits || []) as GitCommit[],
      }));
    } catch {
      setState(prev => ({ ...prev, commits: [] }));
    }
  }, [projectId]);

  // Reset and reload whenever projectId changes
  useEffect(() => {
    if (!projectId) {
      setState(initialGitState);
      return;
    }

    setState({
      ...initialGitState,
      loading: true,
    });

    (async () => {
      try {
        const res = await axios.get(`${API_URL}/git/status/${projectId}`);
        const isRepo = Boolean(res.data?.is_repo);
        let commits: GitCommit[] = [];
        if (isRepo) {
          try {
            const histRes = await axios.get(`${API_URL}/git/history/${projectId}`);
            commits = (histRes.data?.commits || []) as GitCommit[];
          } catch {
            commits = [];
          }
        }
        setState(prev => ({
          ...prev,
          status: res.data,
          isInitialized: isRepo,
          commits,
          loading: false,
        }));
      } catch {
        setState(prev => ({
          ...prev,
          status: null,
          isInitialized: false,
          loading: false,
        }));
      }
    })();
  }, [projectId]);

  const fetchInit = async () => {
    if (!projectId || state.loading) return;
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const res = await axios.post(`${API_URL}/git/init/${projectId}`);
      const isInit = Boolean(res.data?.initialized);
      setState(prev => ({
        ...prev,
        isInitialized: isInit,
        repoPath: res.data?.path || '',
        loading: false,
        error: null,
      }));

      if (res.data?.already_existing) {
        callbacks?.onSuccess?.('Git repository already exists. Status refreshed.');
      } else {
        callbacks?.onSuccess?.('Git repository initialized successfully.');
      }
      await fetchStatus();
      await fetchHistory();
    } catch (err: any) {
      const errorMsg =
        err.response?.data?.detail || err.message || 'Failed to initialize Git repository.';
      setState(prev => ({ ...prev, loading: false, error: errorMsg }));
      callbacks?.onError?.(errorMsg);
    }
  };

  const fetchConnect = async (path: string = '.') => {
    if (!projectId || state.loading) return;
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const res = await axios.post(`${API_URL}/git/connect/${projectId}`, {
        workspace_path: path,
      });
      setState(prev => ({
        ...prev,
        isConnected: Boolean(res.data?.connected),
        repoPath: res.data?.path || '',
        isInitialized: true,
        loading: false,
        error: null,
      }));
      callbacks?.onSuccess?.('Connected to Git repository.');
      await fetchStatus();
      await fetchHistory();
    } catch (err: any) {
      const errorMsg =
        err.response?.data?.detail || err.message || 'Failed to connect to repository.';
      setState(prev => ({ ...prev, loading: false, error: errorMsg }));
      callbacks?.onError?.(errorMsg);
    }
  };

  const fetchDiff = async (staging: boolean) => {
    if (!projectId || state.loading) return;
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const res = await axios.post(`${API_URL}/git/diff/${projectId}`, { staging });
      setState(prev => ({
        ...prev,
        diffContent: res.data?.diff || 'No diff changes found.',
        showDiff: true,
        loading: false,
      }));
    } catch (err: any) {
      const errorMsg = err.response?.data?.detail || err.message || 'Failed to retrieve diff.';
      setState(prev => ({ ...prev, diffContent: '', loading: false, error: errorMsg }));
      callbacks?.onError?.(errorMsg);
    }
  };

  const fetchStage = async (filePaths: string[] = []) => {
    if (!projectId || state.loading) return;
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const res = await axios.post(`${API_URL}/git/stage/${projectId}`, {
        file_paths: filePaths,
      });
      setState(prev => ({
        ...prev,
        stageFiles: res.data?.files || [],
        loading: false,
      }));
      callbacks?.onSuccess?.(
        filePaths.length > 0 ? `Staged ${filePaths.length} file(s).` : 'All changes staged.'
      );
      await fetchStatus();
    } catch (err: any) {
      const errorMsg = err.response?.data?.detail || err.message || 'Failed to stage files.';
      setState(prev => ({ ...prev, loading: false, error: errorMsg }));
      callbacks?.onError?.(errorMsg);
    }
  };

  const fetchUnstage = async (filePaths: string[] = []) => {
    if (!projectId || state.loading) return;
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const res = await axios.post(`${API_URL}/git/unstage/${projectId}`, {
        file_paths: filePaths,
      });
      setState(prev => ({
        ...prev,
        unstageFiles: res.data?.files || [],
        loading: false,
      }));
      callbacks?.onSuccess?.(
        filePaths.length > 0 ? `Unstaged ${filePaths.length} file(s).` : 'All changes unstaged.'
      );
      await fetchStatus();
    } catch (err: any) {
      const errorMsg = err.response?.data?.detail || err.message || 'Failed to unstage files.';
      setState(prev => ({ ...prev, loading: false, error: errorMsg }));
      callbacks?.onError?.(errorMsg);
    }
  };

  const fetchCommit = () => {
    const message = state.commitMessage.trim();
    if (!message || !state.isInitialized || !state.status?.is_repo) return;
    setState(prev => ({ ...prev, showCommitConfirmation: true }));
  };

  const confirmCommit = async () => {
    if (!projectId || !state.isInitialized || !state.status?.is_repo || state.loading) return;
    const message = state.commitMessage.trim();
    if (!message) return;
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const res = await axios.post(`${API_URL}/git/commit/${projectId}`, {
        message,
      });
      if (res.data?.committed) {
        setState(prev => ({
          ...prev,
          commitMessage: '',
          showCommitConfirmation: false,
          loading: false,
        }));
        callbacks?.onSuccess?.(`Commit created: ${res.data.commit_hash} - ${message}`);
        await fetchStatus();
        await fetchHistory();
      } else {
        setState(prev => ({ ...prev, loading: false, showCommitConfirmation: false }));
      }
    } catch (err: any) {
      const errorMsg = err.response?.data?.detail || err.message || 'Commit failed.';
      setState(prev => ({ ...prev, loading: false, error: errorMsg }));
      callbacks?.onError?.(errorMsg);
    }
  };

  const fetchCommitDetails = async (commitHash: string) => {
    if (!projectId || state.loading) return;
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const res = await axios.get(`${API_URL}/git/commit/${projectId}/${commitHash}`);
      setState(prev => ({
        ...prev,
        commitDetails: res.data?.diff || res.data?.stat || 'No diff details available',
        diffContent: res.data?.diff || res.data?.stat || '',
        showDiff: true,
        loading: false,
      }));
    } catch (err: any) {
      const errorMsg =
        err.response?.data?.detail || err.message || 'Failed to fetch commit details.';
      setState(prev => ({ ...prev, commitDetails: '', loading: false, error: errorMsg }));
      callbacks?.onError?.(errorMsg);
    }
  };

  return {
    state,
    setState,
    fetchStatus,
    fetchInit,
    fetchConnect,
    fetchDiff,
    fetchStage,
    fetchUnstage,
    fetchCommit,
    confirmCommit,
    fetchHistory,
    fetchCommitDetails,
  };
}