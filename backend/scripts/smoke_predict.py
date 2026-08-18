import urllib.request
import json

def main():
    req = urllib.request.Request(
        'http://localhost:8000/predict',
        data=b'{"current_stop":"Silk Board","destination":"Marathahalli","limit":5}',
        headers={'Content-Type': 'application/json'}
    )
    res = urllib.request.urlopen(req)
    data = json.loads(res.read())
    print([(a['total_stops'], a['bus_chain'], a['confidence']) for a in data['alternatives']])

if __name__ == "__main__":
    main()
