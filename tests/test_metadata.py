import os
import glob
import rasterio
import datetime
import unittest

class TestNowcastMetadata(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.opt_dir = os.path.join(self.base_dir, '..', 'engine', 'data', 'nowcast_optical_flow')
        self.conv_dir = os.path.join(self.base_dir, '..', 'engine', 'data', 'nowcast_convlstm')

    def check_directory(self, folder):
        files = glob.glob(os.path.join(folder, '*.tif'))
        files.sort()
        self.assertTrue(len(files) > 0, f"No files found in {folder}")
        self.assertEqual(len(files), 12, f"Expected 12 forecast frames, got {len(files)}")
        
        expected_deltas = [30 * (i + 1) for i in range(12)]
        
        for i, f in enumerate(files):
            filename = os.path.basename(f)
            
            try:
                ts_str = filename.replace('.tif', '').split('_')[-2:]
                ts_str = f"{ts_str[0]}_{ts_str[1]}"
                target_time = datetime.datetime.strptime(ts_str, "%Y%m%d_%H%M")
            except Exception as e:
                self.fail(f"Error parsing filename {filename}: {e}")
                
            with rasterio.open(f) as src:
                tags = src.tags()
                base_time_str = tags.get('base_time')
                self.assertIsNotNone(base_time_str, f"[{filename}] MISSING base_time tag!")
                
                try:
                    if base_time_str.endswith('Z'):
                        base_time_dt = datetime.datetime.fromisoformat(base_time_str[:-1])
                    else:
                        base_time_dt = datetime.datetime.fromisoformat(base_time_str)
                        
                    diff = target_time - base_time_dt
                    diff_minutes = int(diff.total_seconds() / 60)
                    
                    self.assertEqual(diff_minutes, expected_deltas[i], 
                                     f"[{filename}] delta {diff_minutes} != expected {expected_deltas[i]}")
                except ValueError as e:
                    self.fail(f"[{filename}] Error parsing base_time '{base_time_str}': {e}")
                    
    def test_optical_flow_metadata(self):
        self.check_directory(self.opt_dir)

    def test_convlstm_metadata(self):
        self.check_directory(self.conv_dir)

if __name__ == '__main__':
    unittest.main()
