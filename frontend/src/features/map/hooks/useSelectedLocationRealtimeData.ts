import { useEffect } from 'react';
import { fetchRealtimeOceanData } from '../api/realtimeOcean';
import { useMapStore } from '../../../store/mapStore';

export function useSelectedLocationRealtimeData() {
  const selectedLocation = useMapStore((s) => s.selectedLocation);
  const setLoading = useMapStore((s) => s.setSelectedLocationDataLoading);
  const setSuccess = useMapStore((s) => s.setSelectedLocationDataSuccess);
  const setError = useMapStore((s) => s.setSelectedLocationDataError);

  useEffect(() => {
    if (!selectedLocation) return;

    const abortController = new AbortController();

    setLoading();

    fetchRealtimeOceanData(selectedLocation, abortController.signal)
      .then((data) => {
        setSuccess(data);
      })
      .catch((error: unknown) => {
        if (abortController.signal.aborted) return;
        setError(error instanceof Error ? error.message : 'Failed to load realtime ocean data');
      });

    return () => {
      abortController.abort();
    };
  }, [selectedLocation, setError, setLoading, setSuccess]);
}
