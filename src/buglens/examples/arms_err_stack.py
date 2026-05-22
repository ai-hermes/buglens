# -*- coding: utf-8 -*-
# This file is auto-generated, don't edit it. Thanks.
import os
import sys
import json

from typing import List

from alibabacloud_arms20190808.client import Client as ARMS20190808Client
from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_arms20190808 import models as arms20190808_models
from alibabacloud_tea_util import models as util_models
from alibabacloud_tea_util.client import Client as UtilClient
from alibabacloud_credentials.models import Config as CredentialConfig
from dotenv import load_dotenv


class Sample:
    def __init__(self):
        pass

    @staticmethod
    def create_client() -> ARMS20190808Client:
        """
        使用凭据初始化账号Client
        @return: Client
        @throws Exception
        """
        # 工程代码建议使用更安全的无AK方式，凭据配置方式请参见：https://help.aliyun.com/document_detail/378659.html。
        credentialsConfig = CredentialConfig(
            type='access_key',
            # 必填参数，此处以从环境变量中获取AccessKey ID为例
            access_key_id=os.environ.get('BUGLENS_ALIBABA_ACCESS_KEY_ID', ''),
            # 必填参数，此处以从环境变量中获取AccessKey Secret为例
            access_key_secret=os.environ.get('BUGLENS_ALIBABA_ACCESS_KEY_SECRET', '')
        )
        credentialsClient = CredentialClient(credentialsConfig)
        config = open_api_models.Config(
            credential=credentialsClient
        )
        # Endpoint 请参考 https://api.aliyun.com/product/ARMS
        config.endpoint = f'arms.cn-hangzhou.aliyuncs.com'
        return ARMS20190808Client(config)

    @staticmethod
    def main(
        args: List[str],
    ) -> None:
        load_dotenv()
        client = Sample.create_client()
        get_rum_exception_stack_request = arms20190808_models.GetRumExceptionStackRequest(
            pid='a7q597fa88@3ecf5e6c7b91ec7',
            exception_stack='245,16085,20',
            exception_binary_images='{"version":"1.0.0","fileName":"index-DXuEeTYs.js.map","uuid":"21be7c88-e56c-4014-b08f-f5b2095dcef1"}',
            region_id='cn-hangzhou',
            sourcemap_type='js'
        )
        runtime = util_models.RuntimeOptions()
        try:
            resp = client.get_rum_exception_stack_with_options(get_rum_exception_stack_request, runtime)
            print(json.dumps(resp, default=str, indent=2))
        except Exception as error:
            # 此处仅做打印展示，请谨慎对待异常处理，在工程项目中切勿直接忽略异常。
            # 错误 message
            print(error.message)
            # 诊断地址
            print(error.data.get("Recommend"))



if __name__ == '__main__':
    Sample.main(sys.argv[1:])
