import os, time

def run(**kwargs):
    device = kwargs.get('device', 'sda')
    stats = {}
    
    if os.path.exists('/proc/diskstats'):
        with open('/proc/diskstats') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 14:
                    dev_name = parts[2]
                    if device in dev_name or dev_name.startswith('sd') or dev_name.startswith('nvme'):
                        reads_completed = int(parts[3])
                        sectors_read = int(parts[5])
                        writes_completed = int(parts[7])
                        sectors_written = int(parts[9])
                        stats[dev_name] = {
                            "reads_completed": reads_completed,
                            "mb_read": round(sectors_read * 512 / (1024 * 1024), 2),
                            "writes_completed": writes_completed,
                            "mb_written": round(sectors_written * 512 / (1024 * 1024), 2)
                        }
                        
    return {
        "status": "HEALTHY",
        "primary_device": device,
        "disks_audited": stats
    }
