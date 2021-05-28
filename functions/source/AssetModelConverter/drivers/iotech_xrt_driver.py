import logging
import os
import time

import boto3
from botocore.exceptions import ClientError

XRT_PREFIX = "xrt/"

log = logging.getLogger('assetModelConverter')
log.setLevel(logging.DEBUG)

class IOTechXRTDriver:
    def __init__(self):
        self.boto3_session = boto3.Session()
        self.dynamoClient = self.boto3_session.resource('dynamodb')
        self.asset_model_table = self.dynamoClient.Table(os.environ['DynamoDB_Model_Table'])
        self.asset_table = self.dynamoClient.Table(os.environ['DynamoDB_Asset_Table'])

        self.dataTypeTable = {
            "Int8": "INTEGER",
            "Int16": "INTEGER",
            "Int32": "INTEGER",
            "Int64": "INTEGER",
            "Uint8": "INTEGER",
            "Uint16": "INTEGER",
            "Uint32": "INTEGER",
            "Uint64": "INTEGER",
            "Float32": "DOUBLE",
            "Float64": "DOUBLE",
            "Boolean": "BOOLEAN",
            "String": "STRING"
        }

        self.models = []
        self.assets = []

    def createDynamoRecords(self, table, data, primaryKey):
        for record in data:
            try:
                table.put_item(Item=record, ConditionExpression=f'attribute_not_exists({primaryKey})')
                time.sleep(0.1)

            except ClientError as cErr:
                if cErr.response['Error']['Code'] == 'ConditionalCheckFailedException':
                    log.info('Ignoring existing record {}'.format(record[primaryKey]))
                else:
                    raise

    def populateAsset(self, device, assets, profiles):
        pname = device["profileName"]
        dname = device.get("name")
        if dname:
            if pname in profiles:
                node = {}
                node["assetName"] = XRT_PREFIX + dname
                node["modelName"] = XRT_PREFIX + pname
                node["change"] = "YES"
                node["tags"] = []
                for dr in profiles[pname]:
                    tag = {}
                    tag["tagName"] = dr
                    tag["tagPath"] = XRT_PREFIX + dname + "/" + dr
                    node["tags"].append (tag)
                assets.append (node)
            else:
                log.error("No profile (" + pname + ") provided for device " + dname)
        else:
            log.error("Un-named device, profile was " + pname)

    def processEvent(self, event):
        profiles = {}
        modelFileData = event['birthData']

        for birth in modelFileData:
            if "deviceResources" in birth:
                res = []
                node = {}
                pname = birth.get("name")
                if pname is None:
                    log.error("Missing name in profile definition, skipped")
                    continue
                node["assetModelName"] = XRT_PREFIX + pname
                node["assetModelHierarchies"] = []
                node["change"] = "YES"
                node["assetModelProperties"] = []

                for dr in birth["deviceResources"]:
                    prop = dr.get("properties")
                    rname = dr.get("name")
                    if rname is None:
                        log.error("Device profile " + pname + ": Missing name in device resource definition, skipped")
                        continue
                    if prop is None:
                        log.error("Device resource " + rname + ": Missing properties, skipped")
                        continue
                    vt = prop.get("valueType")
                    if vt:
                        if vt in self.dataTypeTable:
                            res.append (rname)
                            tag = {
                                "name": rname,
                                "dataType": self.dataTypeTable[vt],
                                "type": { "measurement" : {} }
                            }
                            node["assetModelProperties"].append (tag)
                        else:
                            log.warning("Skipping " + pname + "/" + rname + " of unsupported valueType " + vt)
                    else:
                        log.error("Skipping " + pname + "/" + rname + " of unspecified valueType")

                profiles[pname] = res
                self.models.append (node)

        for birth in modelFileData:
            if "profileName" in birth:
                self.populateAsset (birth, self.assets, profiles)
            else:
                for device in birth:
                    if "profileName" in device:
                        self.populateAsset (device, self.assets, profiles)
                    else:
                        try:
                            if "profileName" in birth[device]:
                                self.populateAsset (birth[device], self.assets, profiles)
                        except TypeError:
                            continue


        self.createDynamoRecords(self.asset_model_table, self.models, 'assetModelName')
        self.createDynamoRecords(self.asset_table, self.assets, 'assetName')

def handler(event, context):
    IOTechXRTDriver().processEvent(event)
